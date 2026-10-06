import type { ReactNode, RefObject } from "react";
import { BrandMark } from "./BrandMark";

interface AppHeaderProps {
  onNewConversation: () => void;
  starting: boolean;
  /** The overflow menu with the demo scenarios (evaluator mode only). */
  menu: ReactNode;
  /** Whether the inspector exists, so there is a drawer to open on narrower screens. */
  hasInspector: boolean;
  drawerOpen: boolean;
  onToggleDrawer: () => void;
  toggleRef: RefObject<HTMLButtonElement | null>;
}

export function AppHeader({
  onNewConversation,
  starting,
  menu,
  hasInspector,
  drawerOpen,
  onToggleDrawer,
  toggleRef,
}: AppHeaderProps) {
  return (
    <header className="appbar">
      <div className="brand">
        <BrandMark size={30} />
        <div className="brand-text">
          <span className="brand-name">ClaimDesk</span>
          <span className="brand-tagline">Guided insurance claims support</span>
        </div>
      </div>
      <div className="appbar-right">
        <span className="env-tag">Demo · synthetic data</span>
        {hasInspector && (
          <button
            ref={toggleRef}
            type="button"
            className="btn drawer-toggle"
            aria-expanded={drawerOpen}
            aria-controls="sop-inspector"
            onClick={onToggleDrawer}
          >
            Workflow inspector
          </button>
        )}
        <button type="button" className="btn" onClick={onNewConversation} disabled={starting}>
          New conversation
        </button>
        {menu}
      </div>
    </header>
  );
}
