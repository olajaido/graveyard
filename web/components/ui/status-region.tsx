/**
 * A polite live region for changes only: a stage change, completion, an error (frontend-design.md section 7).
 * Screen readers read the text whenever it changes, so callers set `message` on a change, never on every poll.
 */
export function StatusRegion({ message }: { message: string }) {
  return (
    <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </div>
  );
}
