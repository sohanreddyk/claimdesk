import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { MoreIcon } from "./icons";
import type { Scenario } from "./scenarios";
import { SCENARIOS } from "./scenarios";

interface ScenarioMenuProps {
  disabled: boolean;
  onPick: (scenario: Scenario) => void;
}

function itemsOf(menu: HTMLElement | null): HTMLElement[] {
  return menu ? Array.from(menu.querySelectorAll<HTMLElement>('[role="menuitem"]')) : [];
}

/** An overflow menu holding the prepared demo scenarios. Choosing one starts a new conversation
 * with the message ready in the box; nothing is sent until the evaluator presses Send. */
export function ScenarioMenu({ disabled, onPick }: ScenarioMenuProps) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    itemsOf(menuRef.current)[0]?.focus();
    function onMouseDown(event: MouseEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || buttonRef.current?.contains(target)) return;
      setOpen(false);
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const items = itemsOf(menuRef.current);
    const index = items.indexOf(document.activeElement as HTMLElement);
    const moveTo = (target: number) => {
      event.preventDefault();
      items[(target + items.length) % items.length]?.focus();
    };
    switch (event.key) {
      case "Escape":
        event.preventDefault();
        setOpen(false);
        buttonRef.current?.focus();
        break;
      case "ArrowDown":
        moveTo(index + 1);
        break;
      case "ArrowUp":
        moveTo(index - 1);
        break;
      case "Home":
        moveTo(0);
        break;
      case "End":
        moveTo(items.length - 1);
        break;
      case "Tab":
        setOpen(false);
        break;
    }
  }

  function choose(scenario: Scenario) {
    setOpen(false);
    buttonRef.current?.focus();
    onPick(scenario);
  }

  return (
    <div className="menu">
      <button
        ref={buttonRef}
        type="button"
        className="icon-btn"
        aria-label="More actions"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <MoreIcon size={16} />
      </button>
      {open && (
        <div
          id={menuId}
          ref={menuRef}
          role="menu"
          aria-label="Demo scenarios"
          className="menu-list"
          onKeyDown={onKeyDown}
        >
          <p className="menu-heading" aria-hidden="true">
            Demo scenarios
          </p>
          {SCENARIOS.map((scenario) => {
            const hintId = `${menuId}-${scenario.id}`;
            return (
              <button
                key={scenario.id}
                type="button"
                role="menuitem"
                tabIndex={-1}
                className="menu-item"
                aria-label={scenario.label}
                aria-describedby={hintId}
                onClick={() => choose(scenario)}
              >
                <span className={`menu-dot dot-${scenario.accent}`} aria-hidden="true" />
                <span className="menu-item-text">
                  <span className="menu-item-label">{scenario.label}</span>
                  <span id={hintId} className="menu-item-hint">
                    {scenario.hint}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
