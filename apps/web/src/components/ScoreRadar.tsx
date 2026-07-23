import { RadarChart, type RadarSeriesOption } from "echarts/charts";
import {
  RadarComponent,
  TooltipComponent,
  type RadarComponentOption,
  type TooltipComponentOption,
} from "echarts/components";
import * as echarts from "echarts/core";
import type { ComposeOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/lib/core";
import { useLocale } from "../lib/i18n";
import type { ScoreMetric } from "../lib/types";

echarts.use([RadarChart, RadarComponent, TooltipComponent, CanvasRenderer]);

type RadarOption = ComposeOption<
  RadarSeriesOption | RadarComponentOption | TooltipComponentOption
>;

export default function ScoreRadar({
  dimensions,
}: {
  dimensions: Record<string, ScoreMetric>;
}) {
  const { isChinese, text } = useLocale();
  const entries = Object.entries(dimensions);
  if (!entries.length) return null;
  return (
    <ReactEChartsCore
      echarts={echarts}
      style={{ height: 360, width: "100%" }}
      opts={{ renderer: "canvas" }}
      option={
        {
          backgroundColor: "transparent",
          tooltip: { trigger: "item" },
          radar: {
            radius: "68%",
            splitNumber: 4,
            indicator: entries.map(([key, value]) => ({
              name: label(key, isChinese),
              max: value.maximum,
            })),
            axisName: { color: "#a8b0a1", fontSize: 10 },
            splitLine: { lineStyle: { color: ["#262d24"] } },
            splitArea: {
              areaStyle: { color: ["rgba(173,255,47,.015)", "transparent"] },
            },
            axisLine: { lineStyle: { color: "#323b2e" } },
          },
          series: [
            {
              type: "radar",
              data: [
                {
                  name: text("得分", "Score"),
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

function label(value: string, isChinese: boolean) {
  const chinese: Record<string, string> = {
    functional_correctness: "功能正确性",
    root_cause_reasoning: "根因推理",
    database_forensics: "数据库取证",
    ci_oracle_analysis: "CI 可信度",
    evidence_quality: "证据质量",
    git_archaeology: "Git 考古",
    patch_engineering: "补丁质量",
    security: "安全",
    tool_resilience: "工具恢复",
    scope_control: "范围控制",
    investigation_report: "调查报告",
    efficiency: "效率",
  };
  if (isChinese && chinese[value]) return chinese[value];
  return value
    .replaceAll("_", " ")
    .split(" ")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}
