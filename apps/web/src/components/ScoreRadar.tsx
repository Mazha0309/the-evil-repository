import { RadarChart, type RadarSeriesOption } from "echarts/charts";
import {
  RadarComponent,
  TooltipComponent,
  type RadarComponentOption,
  type TooltipComponentOption,
} from "echarts/components";
import { type ComposeOption, use as registerCharts } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/lib/core";
import type { ScoreMetric } from "../lib/types";

registerCharts([RadarChart, RadarComponent, TooltipComponent, CanvasRenderer]);

type RadarOption = ComposeOption<
  RadarSeriesOption | RadarComponentOption | TooltipComponentOption
>;

export default function ScoreRadar({
  dimensions,
}: {
  dimensions: Record<string, ScoreMetric>;
}) {
  const entries = Object.entries(dimensions);
  if (!entries.length) return null;
  return (
    <ReactEChartsCore
      style={{ height: 360, width: "100%" }}
      option={
        {
        backgroundColor: "transparent",
        tooltip: { trigger: "item" },
        radar: {
          radius: "68%",
          splitNumber: 4,
          indicator: entries.map(([key, value]) => ({
            name: label(key),
            max: value.maximum,
          })),
          axisName: { color: "#a8b0a1", fontSize: 10 },
          splitLine: { lineStyle: { color: ["#262d24"] } },
          splitArea: { areaStyle: { color: ["rgba(173,255,47,.015)", "transparent"] } },
          axisLine: { lineStyle: { color: "#323b2e" } },
        },
        series: [
          {
            type: "radar",
            data: [
              {
                name: "Score",
                value: entries.map(([, value]) => value.score),
                symbolSize: 5,
                lineStyle: { color: "#adff2f", width: 2 },
                itemStyle: { color: "#adff2f" },
                areaStyle: { color: "rgba(173,255,47,.16)" },
              },
            ],
          },
        ],
        } as RadarOption
      }
    />
  );
}

function label(value: string) {
  return value
    .replaceAll("_", " ")
    .split(" ")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}
