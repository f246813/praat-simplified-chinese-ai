"""规划接口：工具的 JSON Schema、原生 tool calling 的解析、多动作渲染。

参考 Qwen-Agent 的做法（工具自带 JSON Schema，交给服务端做原生 function
calling），本机 llama-server 实测能返回 ``tool_calls``。这些用例守着：

1. 每个工具都有 schema，schema 里的参数名和 ``Tool.signature`` 对得上（防止改
   了工具忘了改 schema）；
2. ``tool_calls`` 能解析成一个或**多个**动作；
3. 服务端什么都没返回时能退回老的 JSON 接口，而不是直接失败；
4. 多个动作按顺序拼成同一条脚本。
"""

import re
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import chat, qwen, tools


CONTEXT_TSV = (
    "id\tclass\tname\tselected\n"
    "1\tSound\tSound tone\t1\n"
)


def signature_names(signature: str) -> set[str]:
    """``Tool.signature`` 里的参数名（把括号里的说明先去掉）。"""

    stripped = re.sub(r"[（(][^）)]*[）)]", "", signature)
    return {piece.strip() for piece in re.split(r"[、，,]", stripped) if piece.strip()}


class ToolSchemaTests(unittest.TestCase):
    def test_every_tool_has_a_schema(self) -> None:
        expected = {tool.name for tool in tools.TOOLS} | {tools.CUSTOM_SCRIPT_TOOL}
        self.assertEqual(set(tools.TOOL_PARAMETERS), expected)

    def test_schema_shape_is_valid(self) -> None:
        for name, schema in tools.TOOL_PARAMETERS.items():
            with self.subTest(tool=name):
                self.assertEqual(schema.get("type"), "object")
                properties = schema.get("properties")
                required = schema.get("required")
                self.assertIsInstance(properties, dict)
                self.assertIsInstance(required, list)
                # 必填项必须是声明过的属性，否则服务端会拒绝这个 schema。
                self.assertTrue(set(required) <= set(properties))
                for key, value in properties.items():
                    self.assertIn("description", value, key)

    def test_schema_parameters_match_the_documented_signature(self) -> None:
        """schema 里的参数名必须出现在工具的 signature 里，防止两边跑偏。"""

        for tool in tools.TOOLS:
            schema = tools.tool_parameters(tool.name)
            documented = signature_names(tool.signature)
            with self.subTest(tool=tool.name):
                self.assertTrue(
                    set(schema["properties"]) <= documented,
                    f"{tool.name}: schema 多出来的参数 "
                    f"{set(schema['properties']) - documented}",
                )
                self.assertTrue(
                    set(schema["required"]) <= documented,
                    f"{tool.name}: 必填项 {schema['required']} 没写在 signature 里",
                )

    def test_schemas_are_openai_shaped(self) -> None:
        schemas = tools.tool_schemas()
        self.assertEqual(len(schemas), len(tools.TOOLS) + 1)
        names = [item["function"]["name"] for item in schemas]
        self.assertEqual(len(names), len(set(names)))
        for item in schemas:
            with self.subTest(tool=item["function"]["name"]):
                self.assertEqual(item["type"], "function")
                self.assertTrue(item["function"]["description"])
                self.assertEqual(item["function"]["parameters"]["type"], "object")

    def test_tool_labels_cover_every_tool(self) -> None:
        labels = tools.tool_labels()
        for tool in tools.TOOLS:
            self.assertIn(tool.name, labels)
        self.assertIn(tools.CUSTOM_SCRIPT_TOOL, labels)


class PlanActionTests(unittest.TestCase):
    def test_actions_from_native_tool_calls_keep_their_order(self) -> None:
        plan = {
            "reply": "查询两个时刻的基频。",
            "actions": [
                {"tool": "pitch", "arguments": {"time": 0.25}},
                {"tool": "pitch", "arguments": {"time": 0.75}},
            ],
        }
        actions = tools.plan_actions(plan)
        self.assertEqual([item["arguments"]["time"] for item in actions], [0.25, 0.75])

    def test_single_tool_plan_is_normalised(self) -> None:
        actions = tools.plan_actions(
            {"reply": "改名。", "tool": "rename_object", "arguments": {"new_name": "a"}}
        )
        self.assertEqual(actions, [
            {"tool": "rename_object", "arguments": {"new_name": "a"}, "script": ""}
        ])

    def test_script_only_plan_becomes_a_custom_script_action(self) -> None:
        actions = tools.plan_actions({"reply": "读文件。", "script": 'Read from file: "x"'})
        self.assertEqual(actions[0]["tool"], tools.CUSTOM_SCRIPT_TOOL)
        self.assertIn("Read from file", actions[0]["arguments"]["script"])

    def test_actions_are_capped(self) -> None:
        plan = {
            "actions": [
                {"tool": "pitch", "arguments": {"time": index}} for index in range(10)
            ]
        }
        self.assertEqual(len(tools.plan_actions(plan)), tools.MAX_ACTIONS_PER_REQUEST)

    def test_empty_plan_has_no_actions(self) -> None:
        self.assertEqual(tools.plan_actions({"reply": "你好。"}), [])


class ToolCallParsingTests(unittest.TestCase):
    def test_arguments_arrive_as_a_json_string(self) -> None:
        message = {
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": "pitch", "arguments": '{"time": 0.4}'},
                }
            ],
        }
        actions = qwen.extract_tool_actions(message)
        self.assertEqual(
            actions,
            [{"tool": "pitch", "arguments": {"time": 0.4}, "id": "call-1"}],
        )

    def test_multiple_calls_are_all_kept(self) -> None:
        message = {
            "tool_calls": [
                {"function": {"name": "pitch", "arguments": '{"time": 0.25}'}},
                {"function": {"name": "pitch", "arguments": '{"time": 0.75}'}},
            ]
        }
        self.assertEqual(len(qwen.extract_tool_actions(message)), 2)

    def test_broken_arguments_do_not_crash(self) -> None:
        message = {"tool_calls": [{"function": {"name": "pitch", "arguments": "not json"}}]}
        self.assertEqual(
            qwen.extract_tool_actions(message),
            [{"tool": "pitch", "arguments": {}, "id": "call-1"}],
        )

    def test_message_without_calls_has_no_actions(self) -> None:
        self.assertEqual(qwen.extract_tool_actions({"content": "你好"}), [])
        self.assertEqual(qwen.extract_tool_actions({}), [])

    def test_planner_mode_env(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(qwen.planner_mode(), qwen.AUTO_MODE)
        with patch.dict("os.environ", {qwen.PLANNER_MODE_ENV: "json"}):
            self.assertEqual(qwen.planner_mode(), qwen.JSON_MODE)
        with patch.dict("os.environ", {qwen.PLANNER_MODE_ENV: "tools"}):
            self.assertEqual(qwen.planner_mode(), qwen.TOOLS_MODE)


class NativePlanningTests(unittest.TestCase):
    """模型只给工具调用时，也能拼出回话和动作。"""

    def setUp(self) -> None:
        self.client = qwen.QwenClient.__new__(qwen.QwenClient)
        self.client.config = qwen.QwenConfig()
        self.client.base_url = "http://127.0.0.1:8000/v1"

    def _plan(self, message: dict, **kwargs) -> dict:
        with patch.object(qwen.QwenClient, "chat_message", return_value=message):
            return self.client.plan_praat_command(
                "查一下基频",
                CONTEXT_TSV,
                [],
                tool_catalog="（工具目录）",
                tool_schemas=tools.tool_schemas(),
                tool_labels=tools.tool_labels(),
                result_path="D:/ai/runtime/chat_result.tsv",
                state_path="D:/ai/runtime/chat_state.txt",
            )

    def test_two_calls_become_two_actions(self) -> None:
        plan = self._plan(
            {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "pitch", "arguments": '{"time": 0.25}'}},
                    {"function": {"name": "pitch", "arguments": '{"time": 0.75}'}},
                ],
            }
        )
        self.assertEqual(len(plan["actions"]), 2)
        self.assertEqual(plan["tool"], "pitch")
        self.assertIn("基频", plan["reply"])

    def test_model_reply_is_used_when_present(self) -> None:
        plan = self._plan(
            {
                "content": "我来看一下这个声音。",
                "tool_calls": [
                    {"function": {"name": "duration", "arguments": "{}"}}
                ],
            }
        )
        self.assertEqual(plan["reply"], "我来看一下这个声音。")

    def test_plain_answer_without_tools_is_not_an_action(self) -> None:
        plan = self._plan({"content": "这个我做不到。"})
        self.assertEqual(plan["tool"], "")
        self.assertEqual(plan["actions"], [])

    def test_nothing_returned_falls_back_to_the_json_planner(self) -> None:
        with patch.object(qwen.QwenClient, "chat_message", return_value={}), patch.object(
            qwen.QwenClient, "_plan_with_json", return_value={"reply": "兜底"} 
        ) as fallback:
            plan = self.client.plan_praat_command(
                "查一下基频",
                CONTEXT_TSV,
                [],
                tool_catalog="（工具目录）",
                tool_schemas=tools.tool_schemas(),
                tool_labels=tools.tool_labels(),
                result_path="D:/ai/runtime/chat_result.tsv",
                state_path="D:/ai/runtime/chat_state.txt",
            )
        self.assertEqual(plan, {"reply": "兜底"})
        fallback.assert_called_once()

    def test_tools_mode_reports_an_empty_response(self) -> None:
        with patch.dict("os.environ", {qwen.PLANNER_MODE_ENV: "tools"}), patch.object(
            qwen.QwenClient, "chat_message", return_value={}
        ):
            with self.assertRaises(qwen.QwenError):
                self.client.plan_praat_command(
                    "查一下基频",
                    CONTEXT_TSV,
                    [],
                    tool_catalog="（工具目录）",
                    tool_schemas=tools.tool_schemas(),
                    result_path="D:/ai/runtime/chat_result.tsv",
                    state_path="D:/ai/runtime/chat_state.txt",
                )


class RenderActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = tools.ToolContext(
            tools.parse_object_context(CONTEXT_TSV),
            Path("D:/ai/runtime/chat_result.tsv"),
            Path("D:/ai/runtime/chat_state.txt"),
        )

    def test_tool_action_renders_a_script(self) -> None:
        script, note = chat.render_action(
            {"tool": "pitch", "arguments": {"time": 0.4}}, self.context
        )
        self.assertEqual(note, "")
        self.assertIn("基频", script)

    def test_unknown_tool_is_an_error(self) -> None:
        with self.assertRaises(tools.ToolError):
            chat.render_action({"tool": "no_such_tool", "arguments": {}}, self.context)

    def test_model_script_rescues_a_bad_argument(self) -> None:
        script, note = chat.render_action(
            {
                "tool": "formant_frequency",
                "arguments": {"formant": 99},
                "script": 'appendFileLine: "D:/ai/runtime/chat_result.tsv", "兜住了"',
            },
            self.context,
        )
        self.assertIn("兜住了", script)
        self.assertIn("改用模型给出的脚本", note)

    def test_custom_script_action_uses_the_script_argument(self) -> None:
        script, note = chat.render_action(
            {
                "tool": tools.CUSTOM_SCRIPT_TOOL,
                "arguments": {"script": 'selectObject: 1\nRename: "x"'},
            },
            self.context,
        )
        self.assertEqual(note, "")
        self.assertIn('Rename: "x"', script)


if __name__ == "__main__":
    unittest.main()
