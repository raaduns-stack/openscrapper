from src.agent.react_controller import Action, Observation, ReActController


def test_react_stops_on_exhaustion():
    controller = ReActController(max_steps=5)
    state = controller.run(Observation(exhausted=True), lambda *_: Observation())
    assert state.stopped
    assert state.step == 1


def test_react_paginates_and_tracks_pages():
    seen = []

    def execute(action, observation):
        seen.append(action)
        return Observation(items=1, next_page=None, exhausted=True)

    state = ReActController(max_steps=5).run(
        Observation(items=2, next_page="page-2"), execute
    )
    assert seen == [Action.PAGINATE]
    assert "page-2" in state.seen_pages


def test_react_has_hard_step_bound():
    counter = {"n": 0}

    def execute(action, observation):
        counter["n"] += 1
        return Observation(items=counter["n"] + 1)

    state = ReActController(max_steps=3).run(Observation(items=1), execute)
    assert state.step == 3
    assert state.stopped
