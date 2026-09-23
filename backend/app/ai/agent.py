"""Bounded, cancellable Responses orchestration; all facts come from tools."""

import asyncio
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.agent_prompts import EXPLANATION_PROMPT, GENERATION_PROMPT, INTERPRET_PROMPT
from app.ai.constraints import merge_intent, validate_constraints
from app.ai.contracts import Constraints, Intent, Narrative
from app.ai.evidence import PROMPT_VERSION, facts_for, ground_narrative, template_narrative
from app.ai.provider import Provider, ProviderError
from app.ai.presentation import public_run
from app.ai.settings import Settings
from app.ai.tools import ToolDispatcher, dataset_version
from app.storage import Store
from app.diagnostics import log_diagnostic, log_exception
from app.models import Decision
from app.simulation.engine import simulate

TERMINAL = {"completed", "failed", "cancelled", "needs_clarification", "interrupted"}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(default="", max_length=2000)
    mode: Literal["ai", "algorithmic"] = "ai"
    operation: Literal["generate", "explain", "compare", "clarify"] | None = None
    current_decisions: list[Decision] = Field(default_factory=list, max_length=5)
    scenario_ids: list[str] = Field(default_factory=list, max_length=3)
    request_id: str = Field(min_length=8, max_length=100)
    constraints: Constraints | None = None


class AgentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def rejection_summary(result: dict[str, Any] | None) -> str:
    """Bounded, validator-authored feedback for both repair progress and final errors."""
    result = result or {}
    issues = list(result.get("errors", []))
    for candidate in result.get("candidates", []):
        if not candidate.get("valid"):
            issues.extend(candidate.get("errors", []))
    messages = list(dict.fromkeys(issue["message"] for issue in issues if issue.get("message")))
    return " ".join(messages[:4])[:1200]


def output_text(response: dict[str, Any]) -> str:
    if response.get("status") == "incomplete":
        raise AgentError("INCOMPLETE_RESPONSE", "Ответ модели не завершён: достигнут лимит вывода или выполнение прервано.")
    texts = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                raise AgentError("MODEL_REFUSAL", "Модель отказалась выполнять этот запрос. Уточните формулировку.")
            if content.get("type") == "output_text":
                texts.append(content.get("text", ""))
    return "\n".join(texts) or response.get("output_text", "")


class AgentManager:
    def __init__(self, settings: Settings, store: Store, provider: Provider):
        self.settings, self.store, self.provider = settings, store, provider
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.transcripts: dict[str, list[dict[str, Any]]] = {}
        self.store.recover_runs()

    def metadata(self, run: dict[str, Any]) -> dict[str, Any]:
        data = self.provider.ledger.metadata(run["run_id"])
        data.update({
            "provider": self.settings.ai_provider,
            "requested_model": self.settings.openai_model,
            "fallback_used": run.get("fallback_used", False),
            "cache_hit": run.get("cache_hit", False),
            "tool_calls": run.get("tool_calls", 0),
            "repair_rounds": run.get("repair_rounds", 0),
            "explanation_repair_rounds": run.get("explanation_repair_rounds", 0),
        })
        if run.get("cache_hit"):
            data["original_generation"] = run.get("original_generation", {})
        return data

    def save(self, session_id: str, run: dict[str, Any]) -> None:
        run["metadata"] = self.metadata(run)
        self.store.put_run(session_id, run["run_id"], run)

    def stage(self, session_id: str, run: dict[str, Any], stage: str, message: str) -> None:
        run.update(status=stage, stage=stage, message=message)
        run["events"].append({"stage": stage, "message": message})
        run["events"] = run["events"][-32:]
        self.save(session_id, run)

    def start(self, session_id: str, request: RunRequest) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        if session is None:
            raise AgentError("SESSION_NOT_FOUND", "Сессия не найдена. Откройте новую сессию.")
        identifier = hashlib.sha256(f"{session_id}:{request.request_id}".encode()).hexdigest()[:32]
        fingerprint = hashlib.sha256(dump(request.model_dump(exclude={"request_id"})).encode()).hexdigest()
        previous = self.store.get_run(session_id, identifier)
        if previous:
            if previous.get("request_fingerprint") != fingerprint:
                raise AgentError("IDEMPOTENCY_CONFLICT", "Этот идентификатор уже использован для другого запроса.")
            return previous
        if sum(not task.done() for task in self.tasks.values()) >= self.settings.ai_max_concurrent_runs:
            raise AgentError("AI_BUSY", "Уже выполняется операция. Дождитесь её завершения или отмените её.")
        constraints = request.constraints or Constraints.model_validate(session.get("constraints") or {})
        run = {
            "run_id": identifier, "status": "queued", "stage": "queued", "message": "Операция принята.",
            "request_fingerprint": fingerprint, "constraints": constraints.model_dump(),
            "scenarios": [], "explanation": None, "events": [], "error": None,
            "clarification": None, "tool_calls": 0, "repair_rounds": 0, "explanation_repair_rounds": 0,
            "cache_hit": False, "fallback_used": False,
        }
        self.save(session_id, run)
        task = asyncio.create_task(self._execute(session_id, request, run))
        self.tasks[identifier] = task
        task.add_done_callback(lambda _: self.tasks.pop(identifier, None))
        return run

    async def cancel(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        run = self.store.get_run(session_id, run_id)
        if run is None or run["status"] in TERMINAL:
            return run
        task = self.tasks.get(run_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        updated = self.store.get_run(session_id, run_id) or run
        if updated["status"] not in TERMINAL:
            self.stage(session_id, updated, "cancelled", "Операция отменена. Уже возникший API-расход не обнуляется.")
        return self.store.get_run(session_id, run_id)

    async def close(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.provider.close()

    def _history(self, session_id: str, role: str, content: str, *, kind: str | None = None) -> None:
        session = self.store.get_session(session_id)
        if session:
            entry = {"role": role, "content": content[:2000]}
            if kind:
                entry["kind"] = kind
            history = session.get("history", []) + [entry]
            self.store.update_session(session_id, history=history[-12:])

    async def _execute(self, session_id: str, request: RunRequest, run: dict[str, Any]) -> None:
        try:
            async with asyncio.timeout(self.settings.ai_run_timeout_seconds):
                await self._work(session_id, request, run)
        except asyncio.CancelledError:
            self.stage(session_id, run, "cancelled", "Операция отменена. Уже возникший API-расход сохраняется.")
        except TimeoutError:
            run["error"] = {"code": "RUN_TIMEOUT", "message": "Истекло время операции. Проверенные варианты, если есть, сохранены."}
            self.stage(session_id, run, "failed", run["error"]["message"])
        except (ProviderError, AgentError) as error:
            run["error"] = {"code": error.code, "message": str(error)}
            if self.settings.ai_allow_template_fallback and run.get("scenarios") and error.code != "MODEL_REFUSAL":
                run["explanation"] = template_narrative(run["scenarios"])
                run["fallback_used"] = True
                self.stage(session_id, run, "completed", "Шаблонное объяснение, без успешного вызова модели для этого объяснения. Причина доступна в ошибке.")
            else:
                self.stage(session_id, run, "failed", str(error))
        except (ValueError, ValidationError, json.JSONDecodeError) as error:
            log_exception(error, run_id=run["run_id"])
            run["error"] = {"code": "INVALID_MODEL_OUTPUT", "message": "Модель вернула неподдерживаемую структуру. Уточните запрос или повторите операцию."}
            self.stage(session_id, run, "failed", run["error"]["message"])
        except Exception as error:
            log_exception(error, run_id=run["run_id"])
            run["error"] = {"code": "AGENT_ERROR", "message": "Операция завершилась внутренней ошибкой. Ручной режим остаётся доступен."}
            self.stage(session_id, run, "failed", run["error"]["message"])
        finally:
            self.transcripts.pop(run["run_id"], None)
            self.save(session_id, run)
            if run.get("error"):
                log_diagnostic(run["error"]["code"], run["error"]["message"], run_id=run["run_id"], secret=self.settings.openai_api_key)
            visible = public_run(run)
            self._history(session_id, "assistant", visible.get("clarification") or (visible.get("explanation") or {}).get("summary") or visible["message"],
                          kind="error" if run["status"] in {"failed", "interrupted"} else None)

    async def _work(self, session_id: str, request: RunRequest, run: dict[str, Any]) -> None:
        constraints = Constraints.model_validate(run["constraints"])
        session = self.store.get_session(session_id)
        history = (session or {}).get("history", [])[-6:]
        self._history(session_id, "user", request.message or {"explain": "Объяснить выбранный сценарий", "compare": "Сравнить выбранные сценарии"}.get(request.operation, "Поиск сценариев"))
        operation = request.operation or "generate"
        if request.mode == "ai" and operation not in {"explain", "compare"}:
            self.stage(session_id, run, "interpreting", "Интерпретируем запрос и сохраняем прежние ограничения.")
            from app.repository import load_repository
            repo = load_repository()
            response = await self.provider.request(run["run_id"], [
                {"role": "system", "content": INTERPRET_PROMPT},
                {"role": "user", "content": dump({"message": request.message, "previous_constraints": constraints.model_dump(), "history": history, "districts": list(repo.district_by_name), "measures": [{"id": m.id, "name": m.name, "type": m.type} for m in repo.measures]})},
            ], text_schema=Intent)
            intent = Intent.model_validate_json(output_text(response))
            if intent.clarification or intent.unsupported_conditions or intent.operation == "clarify":
                run["clarification"] = intent.clarification or "Уточните условие: " + "; ".join(intent.unsupported_conditions)
                self.stage(session_id, run, "needs_clarification", run["clarification"])
                return
            constraints = merge_intent(constraints, intent)
            operation = intent.operation
        validation = validate_constraints(constraints)
        run["constraints"] = constraints.model_dump()
        if not validation["valid"]:
            run["clarification"] = " ".join(item["message"] for item in validation["errors"])
            run["error"] = {"code": "CONSTRAINT_CONTRADICTION" if validation["contradiction"] else "CONSTRAINT_CLARIFICATION", "message": run["clarification"]}
            self.stage(session_id, run, "needs_clarification", run["clarification"])
            return
        self.store.update_session(session_id, constraints=constraints.model_dump())
        dispatcher = ToolDispatcher(self.store, session_id, run["run_id"], constraints, [d.model_dump() for d in request.current_decisions], mode=request.mode, max_candidates=min(3, self.settings.ai_max_candidates))
        if operation in {"explain", "compare"}:
            ids = list(dict.fromkeys(request.scenario_ids))
            if not ids or (operation == "compare" and len(ids) < 2):
                run["clarification"] = "Выберите сохранённый сценарий для объяснения или два сценария для сравнения."
                self.stage(session_id, run, "needs_clarification", run["clarification"])
                return
            rows = [self.store.get_scenario(session_id, identifier) for identifier in ids]
            if any(row is None for row in rows):
                raise AgentError("SCENARIO_NOT_FOUND", "Сценарий не найден в текущей сессии.")
            for row in rows:
                if row["dataset_version"] != dataset_version():
                    raise AgentError("DATASET_CHANGED", "Версия модели изменилась. Пересчитайте решения перед объяснением.")
                result = simulate(row["decisions"])
                if not result["valid"]:
                    raise AgentError("INVALID_SAVED_SCENARIO", "Сохранённые решения не соответствуют правилам модели.")
                row["result"] = result
            run["scenarios"] = rows
        elif request.mode == "algorithmic":
            self.stage(session_id, run, "generating", "Выполняем явно выбранный ограниченный алгоритмический поиск.")
            await dispatcher.dispatch("search_scenarios", {"constraints": constraints.model_dump()})
            run["scenarios"] = dispatcher.scenarios
            self.stage(session_id, run, "completed", "Алгоритмический поиск завершён; глобальный оптимум не гарантирован." if run["scenarios"] else "В пределах ограниченного поиска варианты не найдены; это не доказательство невозможности.")
            return
        else:
            await self._generate(session_id, request, run, dispatcher)
            if run["status"] == "needs_clarification":
                return
            run["scenarios"] = dispatcher.scenarios
        if not run["scenarios"]:
            details = rejection_summary(dispatcher.last_evaluation)
            message = "Модель не сформировала допустимых вариантов в пределах лимитов."
            if details:
                message += f" Причины последней проверки: {details}"
            message += " Это не доказательство отсутствия решений. Можно повторить генерацию или выбрать режим «Алгоритмический поиск» с теми же условиями."
            raise AgentError("NO_VERIFIED_CANDIDATES", message)
        await self._explain(session_id, request, run, constraints)
        count = len(run["scenarios"])
        message = "Ранее сформировано моделью; возвращено из кеша." if run.get("cache_hit") else "Проверенные результаты готовы. Применение возможно только после вашего подтверждения."
        if operation == "generate" and count < constraints.requested_scenario_count:
            message = f"Проверено вариантов: {count}. Дополнительные варианты не получены в пределах лимита; невозможность других решений не доказана."
        self.stage(session_id, run, "completed", message)

    async def _generate(self, session_id: str, request: RunRequest, run: dict[str, Any], dispatcher: ToolDispatcher) -> None:
        context = await dispatcher.dispatch("get_city_context", {})
        messages = [
            {"role": "system", "content": GENERATION_PROMPT},
            {"role": "user", "content": dump({"request": request.message, "constraints": run["constraints"], "city_context": context})},
        ]
        evaluation_rounds = 0
        previous_calls: dict[str, dict[str, Any]] = {}
        pending_outputs: list[dict[str, Any]] = []
        for round_index in range(self.settings.ai_max_model_calls_per_run):
            used_calls = self.provider.ledger.metadata(run["run_id"]).get("api_calls", 0)
            if dispatcher.scenarios and used_calls >= self.settings.ai_max_model_calls_per_run - 1:
                break
            progress = "Модель предлагает черновики."
            if evaluation_rounds:
                progress = "Модель исправляет черновики по ошибкам проверки."
                details = rejection_summary(dispatcher.last_evaluation)
                if details:
                    progress += " " + details
            self.stage(session_id, run, "generating" if not evaluation_rounds else "repairing", progress)
            # The complete city context is already supplied. Start with the
            # candidate tool instead of spending a call fetching it again.
            choice = {"type": "function", "name": "evaluate_scenarios"} if round_index == 0 else "auto"
            response = await self.provider.request(run["run_id"], messages, tools=dispatcher.schemas(), tool_choice=choice)
            text = output_text(response)
            calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
            if not calls:
                if not dispatcher.scenarios and text:
                    run["clarification"] = text[:2000]
                    self.stage(session_id, run, "needs_clarification", "Модель ответила без проверенных вариантов; требуется уточнение.")
                break
            messages.extend(response["output"])
            pending_outputs = [item for item in response["output"] if item.get("type") == "function_call"]
            exceeded = False
            for call in calls:
                call_id, name = call.get("call_id"), call.get("name", "")
                if not call_id:
                    raise AgentError("INVALID_TOOL_CALL", "У вызова инструмента отсутствует call_id.")
                run["tool_calls"] += 1
                signature = name + ":" + call.get("arguments", "")
                result: dict[str, Any]
                if run["tool_calls"] > self.settings.ai_max_tool_calls_per_run:
                    result = {"valid": False, "errors": [{"code": "TOOL_LIMIT", "message": "Достигнут лимит инструментов."}]}
                    exceeded = True
                elif signature in previous_calls:
                    result = {"valid": False, "errors": [{"code": "REPEATED_TOOL_CALL", "message": "Идентичный вызов уже обработан. Используйте его результат и измените черновик."}], "previous_result": previous_calls[signature]}
                else:
                    try:
                        arguments = json.loads(call.get("arguments", ""))
                        if not isinstance(arguments, dict):
                            raise ValueError("arguments must be an object")
                        if name == "evaluate_scenarios":
                            evaluation_rounds += 1
                            run["repair_rounds"] = max(0, evaluation_rounds - 1)
                            if evaluation_rounds > 1 + self.settings.ai_max_repair_rounds:
                                exceeded = True
                                result = {"valid": False, "errors": [{"code": "REPAIR_LIMIT", "message": "Достигнут лимит исправлений."}]}
                            else:
                                self.stage(session_id, run, "validating", "Проверяем правила, пользовательские ограничения и рассчитываем показатели.")
                                result = await dispatcher.dispatch(name, arguments)
                        else:
                            result = await dispatcher.dispatch(name, arguments)
                    except (ValueError, ValidationError, json.JSONDecodeError):
                        result = {"valid": False, "errors": [{"code": "INVALID_TOOL_ARGUMENTS", "message": "Аргументы инструмента не соответствуют JSON-схеме."}]}
                    previous_calls[signature] = result
                function_output = {"type": "function_call_output", "call_id": call_id, "output": dump(result)}
                details = rejection_summary(result)
                if details:
                    log_diagnostic("CANDIDATE_REJECTED" if name == "evaluate_scenarios" else "TOOL_REJECTED", details,
                                   run_id=run["run_id"], secret=self.settings.openai_api_key)
                messages.append(function_output)
                pending_outputs.append(function_output)
                self.store.log_tool(session_id, run["run_id"], name[:100], "processed", {"call_id": call_id, "valid": result.get("valid"), "candidate_count": len(dispatcher.scenarios)})
                run["scenarios"] = dispatcher.scenarios
                self.save(session_id, run)
            if len(dispatcher.scenarios) >= min(run["constraints"]["requested_scenario_count"], self.settings.ai_max_candidates) or exceeded or evaluation_rounds >= 1 + self.settings.ai_max_repair_rounds:
                break
            # Replay the real function_call/output pairs; never use previous_response_id.
            remaining = min(dispatcher.constraints.requested_scenario_count, self.settings.ai_max_candidates) - len(dispatcher.scenarios)
            messages.append({"role": "user", "content": (
                f"Сохраните принятые варианты. Нужно ещё вариантов: {remaining}. "
                f"Расход каждого не должен превышать {context['effective_budget']:g} с учётом резерва. "
                "Исправьте отклонённые по diagnostics и errors: замените состав мер, если превышен бюджет или лимит категории. "
                "Показатели для анализа не требуют выбора конкретных мер. Сохраните все жёсткие ограничения. "
                "Не повторяйте прежние наборы; передайте недостающие варианты одним evaluate_scenarios."
            )})
        # Tool outputs must be returned even when generation has enough variants.
        # _explain uses a fresh explicit context containing all verified tool facts.
        # Older pairs have already been sent in earlier requests. Only the final
        # unanswered batch must accompany the explanation; facts preserve state.
        self.transcripts[run["run_id"]] = pending_outputs

    async def _explain(self, session_id: str, request: RunRequest, run: dict[str, Any], constraints: Constraints) -> None:
        self.stage(session_id, run, "explaining", "Формируем объяснение на основе проверенных фактов.")
        rows = run["scenarios"]
        facts = facts_for(rows, constraints)
        context = {
            "request": request.message, "constraints": constraints.model_dump(),
            "scenario_ids": [row["scenario_id"] for row in rows],
            "scenario_refs": {chr(65 + index): row["scenario_id"] for index, row in enumerate(rows)},
            "scenarios": [{"scenario_id": row["scenario_id"], "name": row["name"], "decisions": row["decisions"]} for row in rows],
            "facts": facts,
        }
        key = hashlib.sha256(dump({"dataset": dataset_version(), "model": self.settings.openai_model, "prompt": PROMPT_VERSION, "context": context}).encode()).hexdigest()
        cached = self.store.cache_get(session_id, key)
        if cached:
            run["explanation"] = cached["explanation"]
            run["cache_hit"] = True
            run["original_generation"] = cached["metadata"]
            run["message"] = "Ранее сформировано моделью; возвращено из кеша."
            return
        if self.settings.ai_allow_template_fallback and (not self.settings.ai_enabled or not self.settings.openai_api_key):
            run["explanation"] = template_narrative(rows)
            run["fallback_used"] = True
            return
        inputs = [{"role": "system", "content": EXPLANATION_PROMPT}]
        transcript = self.transcripts.pop(run["run_id"], [])
        # Include every function output with its call_id in the next Responses request.
        if transcript:
            paired = [item for item in transcript if item.get("type") in {"function_call", "function_call_output"}]
            inputs.extend(paired)
        inputs.append({"role": "user", "content": dump(context)})
        for attempt in range(2):
            response = await self.provider.request(run["run_id"], inputs, text_schema=Narrative)
            narrative = Narrative.model_validate_json(output_text(response))
            try:
                run["explanation"] = ground_narrative(narrative, facts, context["scenario_ids"])
                break
            except ValueError as error:
                log_diagnostic("UNGROUNDED_EXPLANATION", str(error), run_id=run["run_id"], secret=self.settings.openai_api_key)
                used_calls = self.provider.ledger.metadata(run["run_id"]).get("api_calls", 0)
                if attempt or self.settings.ai_max_repair_rounds == 0 or used_calls >= self.settings.ai_max_model_calls_per_run:
                    raise AgentError("UNGROUNDED_EXPLANATION", str(error)) from error
                # Repair the explanation once, inside the same run/cost/time
                # budgets. Rejected prose is never returned or cached as valid.
                run["explanation_repair_rounds"] = 1
                self.stage(session_id, run, "explaining", "Исправляем ссылки и формат чисел в объяснении по проверенным фактам.")
                correction = {"validation_error": str(error), "rejected_draft": narrative.model_dump()}
                inputs = [{"role": "system", "content": EXPLANATION_PROMPT},
                          {"role": "user", "content": dump({**context, "correction": correction})}]
        self.store.cache_set(session_id, key, {"explanation": run["explanation"], "metadata": self.metadata(run)})
