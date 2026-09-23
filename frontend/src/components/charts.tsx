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
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { categories, keys } from "@/lib/ui";
import type { DistrictResult } from "@/lib/types";
import { MeasuredChart } from "./measured-chart";

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
    <MeasuredChart
      className="radar-chart"
      label="Радар пяти направлений: до и после решений"
    >
      {({ width, height }) => (
        <RadarChart width={width} height={height} data={data} outerRadius="70%">
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
            isAnimationActive={false}
          />
          <Radar
            name="После решений"
            dataKey="after"
            stroke="#169b83"
            fill="#35bca0"
            fillOpacity={0.23}
            strokeWidth={2}
            isAnimationActive={false}
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
      )}
    </MeasuredChart>
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
    <MeasuredChart height={height} label={`График: ${labels.join(" и ")}`}>
      {({ width, height: measuredHeight }) => (
        <BarChart
          width={width}
          height={measuredHeight}
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
            isAnimationActive={false}
          />
          <Bar
            name={labels[1]}
            dataKey="after"
            fill="#27ab91"
            radius={[4, 4, 0, 0]}
            maxBarSize={32}
            isAnimationActive={false}
          />
        </BarChart>
      )}
    </MeasuredChart>
  );
}
