import { useEffect, useRef } from "react";

export type ShortcutAction =
  "confirm" | "correct" | "skip" | "undo" | "player" | "next" | "previous";

const KEYS: Record<string, ShortcutAction> = {
  c: "confirm",
  e: "correct",
  s: "skip",
  z: "undo",
  p: "player",
  ArrowRight: "next",
  ArrowLeft: "previous",
};

export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

export function actionFor(event: KeyboardEvent): ShortcutAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  if (isTyping(event.target)) return null;
  return KEYS[event.key] ?? KEYS[event.key.toLowerCase()] ?? null;
}

export function useShortcuts(
  handlers: Partial<Record<ShortcutAction, () => void>>,
  enabled = true,
): void {
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });
  useEffect(() => {
    if (!enabled) return;
    const listener = (event: KeyboardEvent) => {
      const action = actionFor(event);
      const handler = action ? latest.current[action] : undefined;
      if (handler) {
        event.preventDefault();
        handler();
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [enabled]);
}
