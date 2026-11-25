/** First stop of the tab order (WCAG 2.4.1). Targets the `<main id="main">` of every page. */
export function SkipLink() {
  return (
    <a className="skip-link" href="#main">
      Skip to content
    </a>
  );
}
