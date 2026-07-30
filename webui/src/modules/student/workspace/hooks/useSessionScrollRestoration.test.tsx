import { fireEvent, render } from "@testing-library/react";

import { useSessionScrollRestoration } from "./useSessionScrollRestoration";

function ScrollHarness({ sessionId, messages }: { sessionId: string; messages: string[] }) {
  const { scrollRef, onScroll } = useSessionScrollRestoration(sessionId, messages, false);
  return <div ref={scrollRef} onScroll={onScroll} data-testid="thread-scroll">{messages.map((message) => <p key={message}>{message}</p>)}</div>;
}

function setDimensions(element: HTMLElement, scrollHeight: number, clientHeight: number) {
  Object.defineProperties(element, { scrollHeight: { configurable: true, value: scrollHeight }, clientHeight: { configurable: true, value: clientHeight } });
}

describe("useSessionScrollRestoration", () => {
  it("restores each session to its own reading position instead of forcing the bottom", () => {
    const { getByTestId, rerender } = render(<ScrollHarness sessionId="session-a" messages={["a-1"]} />);
    const scroll = getByTestId("thread-scroll");
    setDimensions(scroll, 1200, 400);
    rerender(<ScrollHarness sessionId="session-a" messages={["a-1", "a-2"]} />);

    scroll.scrollTop = 260;
    fireEvent.scroll(scroll);

    setDimensions(scroll, 900, 400);
    rerender(<ScrollHarness sessionId="session-b" messages={["b-1"]} />);
    scroll.scrollTop = 120;
    fireEvent.scroll(scroll);

    setDimensions(scroll, 1200, 400);
    rerender(<ScrollHarness sessionId="session-a" messages={["a-1", "a-2"]} />);

    expect(scroll.scrollTop).toBe(260);
  });
});
