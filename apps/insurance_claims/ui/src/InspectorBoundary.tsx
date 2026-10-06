import { Component } from "react";
import type { ReactNode } from "react";

interface Props {
  /** When this changes after a failure, the next render is tried again. */
  resetKey: unknown;
  children: ReactNode;
}

interface State {
  failed: boolean;
}

/** Keeps a failure inside the evaluator pane from taking the whole page, and so the customer
 * chat, down with it. */
export class InspectorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidUpdate(previous: Props) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (this.state.failed) {
      return (
        <p className="error" role="alert">
          The inspector could not be displayed.
        </p>
      );
    }
    return this.props.children;
  }
}
