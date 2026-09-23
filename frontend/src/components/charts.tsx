"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { categories, keys } from "@/lib/ui";
import type { DistrictResult } from "@/lib/types";

export function DistrictRadar({ district }: { district: DistrictResult }) {
  const data = keys.map((key) => ({
    name: categories[key].label
      .replace("Социальная сфера", "Социум")
      .replace("Городские сервисы", "Сервисы"),
    before:
      categories[key].indicators.reduce(
        (n, k) => n + district.indicators_before[k],
        0,
      ) / 2,
    after:
      categories[key].indicators.reduce(
        (n, k) => n + district.indicators_after[k],
        0,
      ) / 2,
  }));
  return (
    <div
      className="radar-chart"
      role="img"
      aria-label="Радар пяти направлений: до и после решений"
    >
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} outerRadius="70%">
          <PolarGrid stroke="#e2e8ed" />
          <PolarAngleAxis
            dataKey="name"
            tick={{ fill: "#78828f", fontSize: 10 }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 100]}
            tick={false}
            axisLine={false}
          />
          <Radar
            name="До решений"
            dataKey="before"
            stroke="#a4b0c0"
            fill="#dce3eb"
            fillOpacity={0.35}
            strokeDasharray="4 3"
          />
          <Radar
            name="После решений"
            dataKey="after"
            stroke="#169b83"
            fill="#35bca0"
            fillOpacity={0.23}
            strokeWidth={2}
          />
          <Tooltip
            formatter={(value) => Number(value).toFixed(2)}
            contentStyle={{
              borderRadius: 12,
              border: "1px solid #e6ebee",
              fontSize: 12,
            }}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ComparisonChart({
  data,
  labels = ["До решений", "После решений"],
  height = 250,
}: {
  data: { name: string; before: number; after: number }[];
  labels?: [string, string];
  height?: number;
}) {
  return (
    <div
      style={{ height, width: "100%", minWidth: 0 }}
      role="img"
      aria-label={`График: ${labels.join(" и ")}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 15, right: 10, left: -24, bottom: 0 }}
          barGap={4}
        >
          <CartesianGrid vertical={false} stroke="#edf0f3" />
          <XAxis
            dataKey="name"
            tick={{ fill: "#758191", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            interval={0}
          />
          <YAxis
            tick={{ fill: "#758191", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            formatter={(value) => Number(value).toFixed(2)}
            contentStyle={{
              borderRadius: 12,
              border: "1px solid #e6ebee",
              fontSize: 12,
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, paddingTop: 10 }}
            iconType="circle"
            iconSize={7}
          />
          <Bar
            name={labels[0]}
            dataKey="before"
            fill="#bdc9d7"
            radius={[4, 4, 0, 0]}
            maxBarSize={32}
          />
          <Bar
            name={labels[1]}
            dataKey="after"
            fill="#27ab91"
            radius={[4, 4, 0, 0]}
            maxBarSize={32}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
