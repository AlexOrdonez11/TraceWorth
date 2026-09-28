export function Empty({
  title,
  text,
  action,
  button,
}: {
  title: string;
  text: string;
  action: () => void;
  button: string;
}) {
  return (
    <section className="empty-panel">
      <div className="empty-symbol">◫</div>
      <h2>{title}</h2>
      <p>{text}</p>
      <button className="button primary" onClick={action}>
        {button} →
      </button>
    </section>
  );
}
