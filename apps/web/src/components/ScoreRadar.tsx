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
            indicator: entries.map(([key]) => ({
              name: label(key, isChinese),
              max: 100,
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
                  value: entries.map(([, value]) =>
                    value.maximum > 0
                      ? Math.max(
                          0,
                          Math.min(100, (value.score / value.maximum) * 100),
                        )
                      : 0,
                  ),
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
    incident_stabilization: "事故稳定",
    causal_diagnosis: "因果诊断",
    evidence_provenance: "证据溯源",
    environment_forensics: "环境取证",
    objective_reasoning: "客观推理",
    decision_quality: "决策质量",
    self_verification: "自我验证",
    security: "安全",
    tool_resilience: "工具恢复",
    patch_scope: "补丁范围",
    state_management: "状态管理",
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
