import { isValidElement, memo, useEffect, useId, useRef, useState, type ReactElement, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeSanitize, {defaultSchema} from 'rehype-sanitize';
import rehypeKatex from 'rehype-katex';
import rehypeHighlight from 'rehype-highlight';
import DOMPurify from 'dompurify';
import { Copy } from 'lucide-react';
import { IconButton } from './ui';
import type { Rpc } from './types';
import 'katex/dist/katex.min.css';
import 'highlight.js/styles/github-dark.css';
const schema = {...defaultSchema, attributes: {...defaultSchema.attributes, code: [['className', /^language-./, 'math-inline', 'math-display']]}};
let diagramQueue = Promise.resolve();
function Diagram({source}: {source: string}) {
  const id = useId().replace(/[^a-z0-9]/gi, '');
  const [svg, setSvg] = useState(''); const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    setSvg(''); setError('');
    if (source.length > 24000) { setError('图表超过 24,000 字符，请查看源码'); return; }
    diagramQueue = diagramQueue.then(async () => {
      try {
        // Official prebuilt browser ESM and its chunks are copied offline at prebuild.
        const moduleUrl = new URL(`${import.meta.env.BASE_URL}vendor/mermaid/mermaid.esm.min.mjs`, document.baseURI).href;
        const {default: mermaid} = await import(/* @vite-ignore */ moduleUrl) as typeof import('mermaid');
        mermaid.initialize({startOnLoad: false, securityLevel: 'strict', theme: 'neutral', fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif', flowchart: {htmlLabels: false}, suppressErrorRendering: true});
        const result = await mermaid.render(`diagram${id}`, source);
        const clean = DOMPurify.sanitize(result.svg, {USE_PROFILES: {svg: true, svgFilters: true}, FORBID_TAGS: ['foreignObject', 'script', 'a', 'image'], FORBID_ATTR: ['href', 'xlink:href']});
        if (live) setSvg(clean);
      } catch { if (live) setError('图表尚未闭合或格式有误；可展开查看源码'); }
    });
    return () => { live = false; };
  }, [source, id]);
  return <div className="diagram">{svg ? <div role="img" aria-label="Mermaid 图表" dangerouslySetInnerHTML={{__html: svg}} /> : <small>{error || '正在渲染图表…'}</small>}<details><summary>图表源码</summary><pre>{source}</pre></details></div>;
}
function useSmooth(text: string, enabled: boolean) {
  const [visible, setVisible] = useState(text); const visibleRef = useRef(text);
  useEffect(() => {
    let frame = 0;
    if (!enabled || !text.startsWith(visibleRef.current) || matchMedia('(prefers-reduced-motion: reduce)').matches) { visibleRef.current = text; setVisible(text); return; }
    const tick = () => {
      const left = text.length - visibleRef.current.length;
      visibleRef.current = text.slice(0, visibleRef.current.length + Math.max(4, Math.ceil(left / 3)));
      setVisible(visibleRef.current);
      if (left > 0) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick); return () => cancelAnimationFrame(frame);
  }, [text, enabled]);
  return enabled ? visible : text;
}
function CodeBlock({children, language, onError}: {children: ReactNode; language: string; onError: (e: unknown) => void}) {
  const ref = useRef<HTMLPreElement>(null);
  return <div className="code-block"><div className="code-header"><small>{language}</small><IconButton label="复制代码" onClick={() => void navigator.clipboard.writeText(ref.current?.textContent || '').catch(onError)}><Copy size={14}/></IconButton></div><pre ref={ref}>{children}</pre></div>;
}
export const Markdown = memo(function Markdown({text, rpc, onError, smooth = false}: {text: string; rpc: Rpc; onError: (e: unknown) => void; smooth?: boolean}) {
  const visible = useSmooth(text, smooth);
  return <div className="prose"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeSanitize, schema], [rehypeKatex, {trust: false, strict: 'ignore'}], [rehypeHighlight, {detect: false}]]} skipHtml components={{
    a: ({href, children}) => <a href={/^https?:\/\//i.test(href || '') ? href : undefined} onClick={e => { e.preventDefault(); if (href) void rpc('links.open', {url: href}).catch(onError); }}>{children}</a>,
    img: ({alt}) => <span className="blocked-image">[外部图片已阻止：{alt || '图片'}]</span>,
    pre: ({children}) => {
      const code = isValidElement(children) ? children as ReactElement<{className?: string; children?: string}> : null;
      const source = code?.props.children ? String(code.props.children).replace(/\n$/, '') : '';
      if (code?.props.className?.includes('language-mermaid')) return <Diagram source={source} />;
      return <CodeBlock language={code?.props.className?.match(/language-(\w+)/)?.[1] || '代码'} onError={onError}>{children}</CodeBlock>;
    },
  }}>{visible}</ReactMarkdown></div>;
});
