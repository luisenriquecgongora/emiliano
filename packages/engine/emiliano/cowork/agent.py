"""
Autonomous Desktop Cowork Agent Loop.
Executes an Observe-Plan-Act-Verify loop on a pinned window using Windows UI Automation
perception and non-intrusive programmatic Ghost UIA actions.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .actions import ActionSynthesizer, SafetyInterruptedError
from .perception import ScreenPerceiver
from .pinning import WindowPinManager
from .vision import annotated_window_image
from ..direct.client import UnifiedLLMClient

COWORK_SYSTEM_PROMPT = """You are Emiliano's Desktop Cowork Agent.
Your goal is to inspect the UI of the user's pinned application window and take precise actions to accomplish the user's desktop goal.

You have access to the following desktop cowork tools:
- click_element(id: int): Click the UI element by its numeric tag [id]. Uses non-intrusive ghost invocation without moving the mouse cursor.
- click_at(x: int, y: int): Click at screen coordinates (x, y) within the pinned window.
- type_into_element(id: int, text: str): Type text into an input or edit box by its numeric tag [id]. Uses ghost SetValue without synthetic keystrokes.
- press_key(key: str): Press a keyboard key (e.g. Enter, Tab, Escape, Down, Up).
- inspect_window(): Re-scan and refresh the actionable UI elements of the window.
- finish(summary: str): Complete the cowork task and provide the final summary.

To invoke a tool, output a tool call block using either of these formats:

Format 1 (XML - Recommended):
<call:click_element id="1"/>
<call:type_into_element id="2" text="hello"/>
<call:press_key key="Enter"/>
<call:finish summary="Task completed successfully"/>

Format 2 (JSON):
<tool_call>
{"name": "click_element", "arguments": {"id": 1}}
</tool_call>

Workflow Guidelines:
1. Review the currently observed UI elements before every action.
2. Choose the exact element tag [id] matching the user's request.
3. After taking an action, observe the updated UI elements to verify the action succeeded.
4. When the goal is achieved, invoke finish(summary="...") or explain that the task is complete.
"""


# How long the HUD overlay shows a target, and how long the agent waits after showing it
# so a person can see what is about to be clicked before it happens.
HUD_HIGHLIGHT_MS = 1500
HUD_LEAD_SECONDS = 0.35
# click_at has no element, so the overlay marks a small square around the point.
_POINT_BOX = 24

HighlightCallback = Callable[[Dict[str, Any]], Union[Awaitable[None], None]]


def hud_highlight_payload(el: Dict[str, Any], action: str, reasoning: str,
                          duration_ms: int = HUD_HIGHLIGHT_MS) -> Dict[str, Any]:
    """HUD_HIGHLIGHT payload (protocol HUDHighlightPayload) for a tagged element.
    Bounds are physical screen pixels, as UI Automation reports them; the overlay converts."""
    b = el.get("bounds") or {}
    return {
        "element": {
            "id": str(el.get("id", "")),
            "name": el.get("name") or el.get("role") or "element",
            "role": el.get("role"),
            "bounds": {k: int(b.get(k, 0)) for k in ("x", "y", "width", "height")},
            "action": action,
        },
        "reasoning": reasoning,
        "durationMs": duration_ms,
    }


def point_element(x: float, y: float) -> Dict[str, Any]:
    """A pseudo-element for click_at: a small box centred on the clicked point."""
    half = _POINT_BOX // 2
    return {"name": f"({int(x)}, {int(y)})", "role": "Point",
            "bounds": {"x": int(x) - half, "y": int(y) - half, "width": _POINT_BOX, "height": _POINT_BOX}}


def latest_image_only(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A copy of history where only the newest message keeps its screenshot: older ones are out of date and
    would fill a small model's context."""
    last = max((i for i, m in enumerate(history) if m.get("images")), default=-1)
    return [m if i == last or not m.get("images") else {k: v for k, v in m.items() if k != "images"}
            for i, m in enumerate(history)]


def format_ui_elements(elements: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """
    Indexes actionable elements with numeric tags 1..N and computes centers.
    Returns mapping from tag id -> element metadata with computed center.
    """
    tagged: Dict[int, Dict[str, Any]] = {}
    tag_id = 1
    for el in elements:
        role = el.get("role", "Control")
        name = (el.get("name") or "").strip()
        bounds = el.get("bounds") or {}
        w = bounds.get("width", 0)
        h = bounds.get("height", 0)
        if w <= 0 or h <= 0:
            continue
        cx = bounds.get("x", 0) + w // 2
        cy = bounds.get("y", 0) + h // 2
        tagged[tag_id] = {
            "id": tag_id,
            "hwnd": el.get("hwnd"),
            "name": name or role,
            "role": role,
            "action": el.get("action", "click"),
            "bounds": bounds,
            "cx": cx,
            "cy": cy,
        }
        tag_id += 1
    return tagged


def render_elements_text(tagged: Dict[int, Dict[str, Any]]) -> str:
    """Renders tagged elements into concise prompt text for the model."""
    if not tagged:
        return "(No actionable UI elements detected in window)"
    lines = []
    for tag_id, el in tagged.items():
        bounds = el["bounds"]
        lines.append(
            f"[{tag_id}] {el['role']} \"{el['name']}\" at ({el['cx']}, {el['cy']}) "
            f"size=({bounds.get('width')}x{bounds.get('height')}) action={el['action']}"
        )
    return "\n".join(lines)


def parse_cowork_tool_calls(text: str) -> List[Dict[str, Any]]:
    """
    Extracts tool calls from XML <call:...> and JSON <tool_call> formats.
    """
    calls: List[Dict[str, Any]] = []

    # 1. XML empty-element or standard tags: <call:tool_name attr="val".../>
    xml_pattern = re.compile(r'<call:(\w+)([^>]*?)(?:/>|>(.*?)</call:\1>)', re.DOTALL)
    for match in xml_pattern.finditer(text):
        tool_name = match.group(1).strip()
        attrs_str = match.group(2) or ""
        body = (match.group(3) or "").strip()

        args: Dict[str, Any] = {}
        attr_matches = re.findall(r'(\w+)=["\'](.*?)["\']', attrs_str)
        for k, v in attr_matches:
            if v.isdigit():
                args[k] = int(v)
            else:
                args[k] = v

        if body:
            # If body has sub-tags or text, parse
            args["text"] = body

        calls.append({"tool": tool_name, "args": args})

    if calls:
        return calls

    # 2. JSON format: <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    json_blocks = re.findall(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', text, re.DOTALL)
    for block in json_blocks:
        try:
            parsed = json.loads(block)
            name = parsed.get("name")
            arguments = parsed.get("arguments") or {}
            if name:
                calls.append({"tool": name, "args": arguments})
        except Exception:
            pass

    return calls


class CoworkAgentLoop:
    """
    Autonomous Cowork Agent that observes the UI tree, plans actions,
    executes ghost/synthetic actions, and verifies outcomes.
    """

    def __init__(
        self,
        client: UnifiedLLMClient,
        model_id: str,
        pin_manager: Optional[WindowPinManager] = None,
        screen_perceiver: Optional[ScreenPerceiver] = None,
        action_synthesizer: Optional[ActionSynthesizer] = None,
        max_turns: int = 12,
        timeout: float = 120.0,
        vision: bool = False,
        on_highlight: Optional[HighlightCallback] = None,
    ) -> None:
        self.client = client
        # Called with a HUD_HIGHLIGHT payload right before each click or type, so the
        # desktop overlay can show the target; None (CLI, tests) shows nothing.
        self.on_highlight = on_highlight
        # Attach an annotated screenshot to each observation (only for models that accept images)
        self.vision = vision
        self.model_id = model_id
        self.pin_manager = pin_manager or WindowPinManager()
        self.screen_perceiver = screen_perceiver or ScreenPerceiver(pin_manager=self.pin_manager)
        self.action_synthesizer = action_synthesizer or ActionSynthesizer(
            pin_manager=self.pin_manager,
            uia_reader=self.screen_perceiver._uia,
            ghost_mode=True,
        )
        self.max_turns = max_turns
        self.timeout = timeout
        self.tagged_elements: Dict[int, Dict[str, Any]] = {}
        self.last_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

    def observe(self, hwnd: Optional[int] = None) -> str:
        """Reads actionable elements from target window and updates internal tagged mapping."""
        target_hwnd = hwnd or self.pin_manager.pinned_hwnd
        raw_elements = self.screen_perceiver.get_ui_elements(hwnd=target_hwnd)
        self.tagged_elements = format_ui_elements(raw_elements)
        return render_elements_text(self.tagged_elements)

    def snapshot(self, hwnd: Optional[int] = None) -> Optional[Tuple[str, str]]:
        """(base64 screenshot, prompt note) of the window as last observed, or None without vision."""
        if not self.vision:
            return None
        try:
            return annotated_window_image(self.screen_perceiver, self.pin_manager,
                                          hwnd or self.pin_manager.pinned_hwnd, self.tagged_elements)
        except Exception as e:  # a failed capture must never stop the task: the element list still works
            logger.warning(f"[CoworkAgent] Screenshot failed: {e}")
            return None

    async def highlight(self, el: Dict[str, Any], action: str, reasoning: str) -> None:
        """Shows the target on the HUD overlay, then pauses briefly. Never raises: a missing or
        broken overlay must not stop the action."""
        if not self.on_highlight:
            return
        try:
            result = self.on_highlight(hud_highlight_payload(el, action, reasoning))
            if inspect.isawaitable(result):
                await result
            await asyncio.sleep(HUD_LEAD_SECONDS)
        except Exception as e:
            logger.warning(f"[CoworkAgent] HUD highlight failed: {e}")

    async def execute_tool(self, tool_name: str, args: Dict[str, Any], hwnd: Optional[int] = None) -> str:
        """Executes a cowork action and observes resulting UI state."""
        try:
            if tool_name == "click_element":
                el_id = int(args.get("id", 0))
                if el_id not in self.tagged_elements:
                    return f"Error: Element tag [{el_id}] not found. Current elements:\n{render_elements_text(self.tagged_elements)}"
                el = self.tagged_elements[el_id]
                await self.highlight(el, "click", f"Clicking {el['role']} '{el['name']}'")
                self.action_synthesizer.click(x=el["cx"], y=el["cy"])
                await asyncio.sleep(0.3)
                new_state = self.observe(hwnd=hwnd)
                return f"Success: Clicked {el['role']} '{el['name']}' at ({el['cx']}, {el['cy']}).\nUpdated UI:\n{new_state}"

            elif tool_name == "click_at":
                x = float(args.get("x", 0))
                y = float(args.get("y", 0))
                await self.highlight(point_element(x, y), "click", f"Clicking at ({int(x)}, {int(y)})")
                self.action_synthesizer.click(x=x, y=y)
                await asyncio.sleep(0.3)
                new_state = self.observe(hwnd=hwnd)
                return f"Success: Clicked at ({x}, {y}).\nUpdated UI:\n{new_state}"

            elif tool_name == "type_into_element":
                el_id = int(args.get("id", 0))
                text = str(args.get("text", ""))
                if el_id not in self.tagged_elements:
                    return f"Error: Element tag [{el_id}] not found."
                el = self.tagged_elements[el_id]
                await self.highlight(el, "type", f"Typing into {el['role']} '{el['name']}'")
                self.action_synthesizer.type_text(text=text, x=el["cx"], y=el["cy"])
                await asyncio.sleep(0.3)
                new_state = self.observe(hwnd=hwnd)
                return f"Success: Typed '{text}' into {el['role']} '{el['name']}'.\nUpdated UI:\n{new_state}"

            elif tool_name == "press_key":
                key = str(args.get("key", "Enter"))
                self.action_synthesizer.press_key(key)
                await asyncio.sleep(0.3)
                new_state = self.observe(hwnd=hwnd)
                return f"Success: Pressed key '{key}'.\nUpdated UI:\n{new_state}"

            elif tool_name == "inspect_window":
                new_state = self.observe(hwnd=hwnd)
                return f"Current UI elements:\n{new_state}"

            elif tool_name == "finish":
                summary = str(args.get("summary", "Cowork task completed."))
                return f"Task completed: {summary}"

            else:
                return f"Error: Unknown tool '{tool_name}'."

        except SafetyInterruptedError as e:
            logger.warning(f"[CoworkAgent] Safety check interrupted action: {e}")
            return f"Safety error: Action halted: {e}"
        except Exception as e:
            logger.error(f"[CoworkAgent] Tool execution failure: {e}")
            return f"Error executing {tool_name}: {e}"

    async def run(
        self,
        goal: str,
        hwnd: Optional[int] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        reasoning: Optional[bool] = None,
    ) -> str:
        """
        Runs the Cowork Observe-Plan-Act-Verify loop.
        """
        target_hwnd = hwnd or self.pin_manager.pinned_hwnd
        initial_ui = self.observe(hwnd=target_hwnd)

        pinned_title = self.pin_manager.pinned_title or (f"HWND {target_hwnd}" if target_hwnd else "Desktop")
        prompt = (
            f"Goal: {goal}\n\n"
            f"Target Pinned Window: {pinned_title}\n"
            f"Currently Observed UI Elements:\n{initial_ui}\n\n"
            f"Plan and execute the actions needed to achieve the goal."
        )

        first: Dict[str, Any] = {"role": "user", "content": prompt}
        snap = self.snapshot(target_hwnd)
        if snap:
            first["content"] += f"\n\n{snap[1]}"
            first["images"] = [snap[0]]
        history: List[Dict[str, Any]] = [
            {"role": "system", "content": COWORK_SYSTEM_PROMPT},
            first,
        ]

        full_output_parts: List[str] = []

        for turn in range(self.max_turns):
            logger.info(f"[CoworkAgent] Turn {turn + 1}/{self.max_turns} on {self.model_id}")
            turn_chunks: List[str] = []

            async for chunk in self.client.stream_completion(
                messages=latest_image_only(history),
                model_name=self.model_id,
                timeout=self.timeout,
                on_reasoning=on_reasoning,
                think=reasoning,
            ):
                turn_chunks.append(chunk)
                if on_chunk:
                    on_chunk(chunk)

            turn_text = "".join(turn_chunks)
            full_output_parts.append(turn_text)

            if self.client.last_usage:
                self.last_usage["prompt_tokens"] += self.client.last_usage.get("prompt_tokens", 0)
                self.last_usage["completion_tokens"] += self.client.last_usage.get("completion_tokens", 0)

            tool_calls = parse_cowork_tool_calls(turn_text)
            if not tool_calls:
                logger.info(f"[CoworkAgent] No tool calls on turn {turn + 1}; task finished")
                break

            # Check if finish was called
            if any(call["tool"] == "finish" for call in tool_calls):
                logger.info("[CoworkAgent] Agent called finish; task completed")
                break

            history.append({"role": "assistant", "content": turn_text})

            tool_responses: List[str] = []
            for call in tool_calls:
                tool_name = call["tool"]
                args = call["args"]
                logger.info(f"[CoworkAgent] Executing: {tool_name}({args})")
                if on_chunk:
                    on_chunk(f"\n⚡ [Cowork Action: {tool_name} {args}]\n")

                result = await self.execute_tool(tool_name, args, hwnd=target_hwnd)
                tool_responses.append(f"<tool_response name=\"{tool_name}\">\n{result}\n</tool_response>")

            tool_feedback = "\n\n".join(tool_responses)
            if on_chunk:
                on_chunk(f"\n{tool_feedback}\n")

            feedback: Dict[str, Any] = {"role": "user", "content": tool_feedback}
            snap = self.snapshot(target_hwnd)
            if snap:
                feedback["content"] += f"\n\n{snap[1]}"
                feedback["images"] = [snap[0]]
            history.append(feedback)

        return "\n".join(full_output_parts)
