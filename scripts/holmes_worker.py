from __future__ import annotations

import argparse
import os
from pathlib import Path

from holmes.core.llm import DefaultLLM
from holmes.core.prompt import build_initial_ask_messages
from holmes.core.tool_calling_llm import ToolCallingLLM
from holmes.core.tools import ToolsetStatusEnum
from holmes.core.tools_utils.tool_executor import ToolExecutor
from holmes.plugins.toolsets.grafana.loki.toolset_grafana_loki import GrafanaLokiToolset
from holmes.plugins.toolsets.grafana.toolset_grafana_tempo import GrafanaTempoToolset
from holmes.plugins.toolsets.prometheus.prometheus import PrometheusToolset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("model")
    parser.add_argument("prompt")
    parser.add_argument("output", type=Path)
    parser.add_argument("--investigate", action="store_true")
    args = parser.parse_args()

    tools = [PrometheusToolset(), GrafanaLokiToolset(), GrafanaTempoToolset()]
    for tool, config in zip(tools, [
        {"prometheus_url": args.url + "/"},
        {"api_url": args.url},
        {"api_url": args.url},
    ], strict=True):
        tool.config = config
        tool.check_prerequisites(silent=True)
        if tool.status != ToolsetStatusEnum.ENABLED:
            raise RuntimeError(f"HolmesGPT toolset {tool.name} unavailable: {tool.error}")

    executor = ToolExecutor(tools)
    llm = DefaultLLM(
        model=f"nvidia_nim/{args.model}",
        api_key=os.environ["NVIDIA_NIM_API_KEY"],
        api_base=f"{args.url}/v1",
        args={"num_retries": 0, "max_tokens": 8192, "temperature": 0},
    )
    worker = ToolCallingLLM(
        tool_executor=executor, max_steps=10 if args.investigate else 4,
        llm=llm, tool_results_dir=None,
    )
    messages = build_initial_ask_messages(args.prompt, None, executor)
    result = worker.call(
        messages, response_format=None if args.investigate else {"type": "json_object"},
    )
    args.output.write_text(result.model_dump_json())


if __name__ == "__main__":
    main()
