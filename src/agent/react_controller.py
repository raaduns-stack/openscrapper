"""Bounded ReAct-style controller for autonomous collection decisions."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Action(str, Enum):
    OBSERVE = "observe"
    COLLECT = "collect"
    PAGINATE = "paginate"
    STOP = "stop"


@dataclass(frozen=True)
class Observation:
    items: int = 0
    next_page: str | None = None
    exhausted: bool = False
    error: str | None = None


@dataclass
class ReActState:
    step: int = 0
    seen_pages: set[str] = field(default_factory=set)
    observations: list[Observation] = field(default_factory=list)
    stopped: bool = False


class ReActController(Generic[T]):
    """Observe → evaluate → choose → execute, with bounded progress."""
    def __init__(self, max_steps: int = 20):
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        self.max_steps = max_steps

    def choose(self, observation: Observation, state: ReActState) -> Action:
        if observation.error or observation.exhausted:
            return Action.STOP
        if observation.next_page and observation.next_page not in state.seen_pages:
            return Action.PAGINATE
        if observation.items > 0:
            return Action.COLLECT
        return Action.STOP

    def run(self, initial: Observation, execute: Callable[[Action, Observation], Observation]) -> ReActState:
        state = ReActState()
        observation = initial
        while state.step < self.max_steps and not state.stopped:
            state.step += 1
            state.observations.append(observation)
            action = self.choose(observation, state)
            if action is Action.STOP:
                state.stopped = True
                break
            if action is Action.PAGINATE and observation.next_page:
                state.seen_pages.add(observation.next_page)
            next_observation = execute(action, observation)
            if action is Action.COLLECT and next_observation == observation:
                state.stopped = True
                break
            if next_observation == observation:
                state.stopped = True
                break
            observation = next_observation
        if state.step >= self.max_steps:
            state.stopped = True
        return state
