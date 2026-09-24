export function Brand({href = '/', tag}: {href?: string; tag?: string}) {
  return <a className="brand" href={href}><img src="/favicon.svg" width={30} height={30} alt=""/>TraceWorth{tag && <span className="brand-tag">{tag}</span>}</a>;
}
