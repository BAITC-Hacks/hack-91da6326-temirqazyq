"""Автогенерация одностраничной презентации решения команды (HTML, печатается в PDF)."""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

from .engine.data import Dataset, load_dataset
from .engine.models import Decision, ScoreResult


def _e(x: Any) -> str:
    return html.escape(str(x))


def render_report(team: str, decisions: List[Decision], result: ScoreResult, analysis: Optional[Dict[str, Any]], event_title: Optional[str], ds: Optional[Dataset] = None) -> str:
    ds = ds or load_dataset()
    mm, dm = ds.measure_map, ds.district_map
    rows = "".join(
        f"<tr><td>{_e(m.measure_id)}</td><td>{_e(m.name)}</td><td>{_e(dm[m.district_id].name if m.district_id else 'весь город')}</td>"
        f"<td class='num'>{m.cost}</td><td class='num'>{m.lag}</td><td class='num {'pos' if m.marginal_score >= 0 else 'neg'}'>{m.marginal_score:+.2f}</td></tr>"
        for m in result.measures
    )
    dist_rows = "".join(
        f"<tr><td>{_e(d.name)}</td><td class='num'>{d.score_before:.1f}</td><td class='num'>{d.score_after:.1f}</td><td class='num {'pos' if d.score_after - d.score_before >= 0 else 'neg'}'>{d.score_after - d.score_before:+.1f}</td>"
        f"<td>{_e(', '.join(f'{i.code} {i.delta:+.1f}' for i in d.indicators if abs(i.delta) > 1e-9) or '—')}</td></tr>"
        for d in result.districts
    )
    an = (analysis or {}).get("analyst") or {}
    cr = (analysis or {}).get("critic") or {}
    ad = (analysis or {}).get("advisor") or {}
    orc = (analysis or {}).get("oracle") or {}

    def ul(items: List[str]) -> str:
        return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>" if items else "<p class='muted'>—</p>"

    recs = "".join(
        f"<li><b>{_e(r.get('title', ''))}</b> — {_e(r.get('change', ''))}: Score {r.get('new_score', '?')} ({r.get('gain', 0):+}) при стоимости {r.get('cost', '?')}</li>"
        for r in (ad.get("recommendations") or [])[:3]
    )
    synergies = ", ".join(s.note for s in result.synergies) or "нет"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Аким на 5 часов — {_e(team)}</title>
<style>
body{{font-family:Inter,system-ui,Segoe UI,Roboto,sans-serif;margin:0;padding:32px 40px;color:#14213d;background:#fff;max-width:1000px}}
h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:#4a5568;margin:26px 0 8px}}
.sub{{color:#4a5568;margin:0 0 18px}} .kpi{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}
.kpi div{{border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px}} .kpi b{{display:block;font-size:24px}} .kpi span{{font-size:12px;color:#4a5568}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #e2e8f0;padding:6px 8px;text-align:left}} th{{background:#f7fafc;font-weight:600}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .pos{{color:#15803d}} .neg{{color:#b91c1c}} .muted{{color:#718096}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:24px}} ul{{margin:4px 0;padding-left:18px}} li{{margin:3px 0}}
.quote{{border-left:3px solid #f59e0b;padding:6px 12px;background:#fffbeb;font-style:italic}}
@media print{{body{{padding:12mm}} .kpi div{{break-inside:avoid}}}}
</style></head><body>
<h1>Аким на 5 часов — сценарий команды «{_e(team)}»</h1>
<p class="sub">{_e(an.get('headline') or 'Astana Quality of Life Score')}{(' · Событие: ' + _e(event_title)) if event_title else ''}</p>
<div class="kpi">
<div><b>{result.score}</b><span>Итоговый Score (база {result.base_score}, {result.delta:+})</span></div>
<div><b>{result.total_cost}/{result.budget}</b><span>Потрачено бюджета, остаток {result.remaining}</span></div>
<div><b>{result.d_avg:.1f}</b><span>Средний балл районов (70% веса)</span></div>
<div><b>{result.d_min:.1f}</b><span>Слабейший район: {_e(dm[result.d_min_district].name)} (30% веса)</span></div>
<div><b>{result.n_crit}</b><span>Критических показателей (было {result.base_n_crit})</span></div>
</div>
<h2>Пять решений</h2>
<table><tr><th>ID</th><th>Мероприятие</th><th>Где</th><th class="num">Стоимость</th><th class="num">Лаг</th><th class="num">Вклад в Score</th></tr>{rows}</table>
<p class="muted">Синергии: {_e(synergies)}.{(' Оракул: максимум ' + str(orc.get('best_score')) + ', разрыв ' + str(orc.get('gap_to_best')) + ', перцентиль ' + str(orc.get('percentile')) + '%.') if orc else ''}</p>
<h2>Районы до и после</h2>
<table><tr><th>Район</th><th class="num">До</th><th class="num">После</th><th class="num">Δ</th><th>Изменённые показатели</th></tr>{dist_rows}</table>
<div class="cols">
<div><h2>Сильные стороны</h2>{ul(an.get('strengths') or [])}<h2>Компромиссы</h2>{ul(an.get('tradeoffs') or [])}</div>
<div><h2>Риски</h2>{ul(an.get('risks') or [])}<h2>Замечания критика</h2>{ul([w.get('title', '') + ': ' + w.get('detail', '') for w in (cr.get('weaknesses') or [])])}</div>
</div>
<h2>Как улучшить</h2><ul>{recs or '<li class="muted">—</li>'}</ul>
{('<h2>Голос жителя</h2><p class="quote">' + _e(an['resident_voice'].get('district', '')) + ': «' + _e(an['resident_voice'].get('quote', '')) + '»</p>') if an.get('resident_voice') else ''}
<p class="muted">Сгенерировано AI-симулятором «Аким на 5 часов». Числа посчитаны детерминированным движком; текст — {('LLM (' + _e((analysis or {}).get('llm', {}).get('model'))) + ')' if an.get('_mode') == 'llm' else 'шаблонный режим без LLM'}.</p>
</body></html>"""
