import { useEffect, useRef, useState } from 'react';
import { ComposerPrimitive, AttachmentPrimitive, useAuiState, type ThreadComposerRuntime } from '@assistant-ui/react';
import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Bold, Italic, Code, List, Paperclip, ArrowUp, Square, X, FileText } from 'lucide-react';
import { InputHistory, markdownParser, markdownSerializer, shouldSend } from './editor';
import { ChatStore, useChatState } from './store';
import type { Attachment, Preview, Session } from './types';
import { readOnly } from './types';
import { IconButton, Modal } from './ui';
import { safePreviewUrl } from './bridge';
import { ComposerStatus } from './ComposerStatus';
export const attachmentDescriptor = (a: Attachment) => ({id: a.id, type: a.mime.startsWith('image/') ? 'image' : 'file', name: a.name, contentType: a.mime, content: []});
export function AttachmentPreview({preview, onClose}: {preview: Preview; onClose: () => void}) {
  const url = safePreviewUrl(preview.dataUrl);
  return <Modal title={preview.name} onClose={onClose}><p className="muted">{preview.mime}</p>{preview.text !== undefined && <pre className="preview-text">{preview.text}</pre>}{url && (preview.mime.startsWith('image/') ? <img className="preview-image" alt={preview.name} src={url}/> : preview.mime.startsWith('audio/') ? <audio controls src={url}/> : null)}{!url && preview.text === undefined && <p>此格式没有安全预览。附件可提交，由宿主校验处理；不会在前端执行或打开文件。</p>}</Modal>;
}
export function Composer({store, session, composer, onSettings}: {store: ChatStore; session: Session; composer: ThreadComposerRuntime; onSettings: () => void}) {
  const state = useChatState(store); const [busy, setBusy] = useState(false); const [preview, setPreview] = useState<Preview>();
  const form = useRef<HTMLFormElement>(null); const composing = useRef(false); const compositionEnd = useRef(-Infinity); const history = useRef(new InputHistory());
  const latest = useRef({mode: String(state.boot?.settings.preferences.send_key || 'enter'), disabled: readOnly(session)});
  latest.current = {mode: String(state.boot?.settings.preferences.send_key || 'enter'), disabled: readOnly(session)};
  const editor = useEditor({
    extensions: [StarterKit.configure({underline: false, link: {openOnClick: false, autolink: false}})],
    content: '', immediatelyRender: true,
    editorProps: {
      attributes: {role: 'textbox', 'aria-label': '消息输入', 'aria-multiline': 'true', 'data-placeholder': '描述你的分析目标，或附上音频与材料…', spellcheck: 'false'},
      handleKeyDown: (view, event) => {
        const ime = composing.current || view.composing || event.isComposing || event.keyCode === 229;
        if (ime || performance.now() - compositionEnd.current < 90) return false;
        if (shouldSend(event, latest.current.mode, ime, false)) { event.preventDefault(); form.current?.requestSubmit(); return true; }
        if ((event.key === 'ArrowUp' || event.key === 'ArrowDown') && !event.ctrlKey && !event.metaKey && !event.shiftKey && (event.altKey || !view.state.doc.textContent.trim())) {
          const entries = (store.getSnapshot().messages[session.id] || []).filter(m => m.role === 'user' && m.content.trim()).map(m => m.content).reverse();
          const current = composer.getState().text;
          const recalled = history.current.navigate(event.key === 'ArrowUp' ? 'older' : 'newer', current, entries);
          if (recalled !== undefined) { event.preventDefault(); composer.setText(recalled); return true; }
        }
        return false;
      },
      handlePaste: (_view, event) => {
        const files = Array.from(event.clipboardData?.files || []);
        if (!files.length) return false;
        event.preventDefault(); void addFiles(files); return true;
      },
      handleDrop: (_view, event) => {
        const files = Array.from(event.dataTransfer?.files || []);
        if (!files.length) return false;
        event.preventDefault(); void addFiles(files); return true;
      },
    },
    onUpdate: ({editor}) => composer.setText(markdownSerializer.serialize(editor.state.doc)),
  });
  async function addFiles(files: File[]) {
    if (latest.current.disabled) return;
    setBusy(true);
    try { for (const file of files) await composer.addAttachment(file); }
    catch (e) { store.report(e); } finally { setBusy(false); }
  }
  useEffect(() => {
    if (!editor) return;
    const sync = () => {
      const text = composer.getState().text;
      if (markdownSerializer.serialize(editor.state.doc) !== text && !editor.view.composing) {
        editor.commands.setContent(markdownParser(editor.schema).parse(text).toJSON(), {emitUpdate: false});
        editor.commands.setTextSelection(editor.state.doc.content.size - 1);
      }
      const attachments = composer.getState().attachments;
      // Persist only imported metadata per UI session; not File bytes or Base64.
      store.attachments.set(session.id, attachments.filter(a => a.status.type !== 'running').map(a => ({id: a.id, name: a.name, mime: a.contentType || 'application/octet-stream', size: 0})));
    };
    sync(); return composer.subscribe(sync);
  }, [composer, editor, store, session.id]);
  useEffect(() => { editor?.setEditable(!readOnly(session) && !state.submitting[session.id]); }, [editor, session.readOnly, session.id, state.submitting[session.id]]);
  const choose = async () => {
    setBusy(true);
    try { const attachments = await store.rpc('attachments.choose', {}); for (const a of attachments) await composer.addAttachment(attachmentDescriptor(a)); }
    catch (e) { store.report(e); } finally { setBusy(false); }
  };
  const NativeAttachment = useRef(function NativeAttachment() {
    const attachment = useAuiState(s => s.attachment);
    return <AttachmentPrimitive.Root className="attachment-chip"><button type="button" onClick={() => void store.rpc('attachments.preview',{attachmentId: attachment.id}).then(setPreview).catch(store.report)}><FileText size={14}/><span>{attachment.name}</span>{attachment.status.type === 'running' && <small>导入中</small>}{attachment.status.type === 'incomplete' && <small>导入失败</small>}</button><AttachmentPrimitive.Remove aria-label={`移除 ${attachment.name}`} title={`移除 ${attachment.name}`}><X size={13}/></AttachmentPrimitive.Remove></AttachmentPrimitive.Root>;
  }).current;
  if (readOnly(session)) return <footer className="readonly-footer">旧记录只读 · 不恢复或重放旧操作 <button onClick={() => void store.create().catch(store.report)}>新建会话继续</button></footer>;
  return <div className="composer-zone"><ComposerPrimitive.Root ref={form} className="composer" onSubmitCapture={e => { if (composing.current || performance.now() - compositionEnd.current < 90 || busy) e.preventDefault(); }} onDrop={e => { if (e.dataTransfer.files.length) { e.preventDefault(); e.stopPropagation(); void addFiles(Array.from(e.dataTransfer.files)); } }} onDragOver={e => { if (e.dataTransfer.types.includes('Files')) e.preventDefault(); }}>
    <div className="editor-toolbar" role="toolbar" aria-label="文本格式"><IconButton label="加粗（Ctrl+B）" aria-pressed={editor?.isActive('bold')} onClick={() => editor?.chain().focus().toggleBold().run()}><Bold size={15}/></IconButton><IconButton label="斜体（Ctrl+I）" onClick={() => editor?.chain().focus().toggleItalic().run()}><Italic size={15}/></IconButton><IconButton label="行内代码" onClick={() => editor?.chain().focus().toggleCode().run()}><Code size={15}/></IconButton><IconButton label="项目列表" onClick={() => editor?.chain().focus().toggleBulletList().run()}><List size={15}/></IconButton></div>
    <div onInputCapture={e => { if (!(e.nativeEvent as InputEvent).isComposing) composing.current = false; }} onCompositionStartCapture={() => { composing.current = true; }} onCompositionEndCapture={() => { composing.current = false; compositionEnd.current = performance.now(); }}><EditorContent editor={editor}/></div><div className="attachment-list"><ComposerPrimitive.Attachments components={{Attachment: NativeAttachment}}/></div>
    <div className="composer-actions"><button type="button" className="attach-button" disabled={busy} onClick={() => void choose()}><Paperclip size={16}/>{busy ? '导入中…' : '添加附件'}</button><ComposerStatus store={store} session={session} composer={composer} onSettings={onSettings}/><ComposerPrimitive.Cancel className="stop-button" aria-label="取消当前任务"><Square size={15}/>停止</ComposerPrimitive.Cancel><ComposerPrimitive.Send className="send-button" aria-label="发送消息" disabled={busy} onClickCapture={e => { if (composing.current || editor?.view.composing || performance.now() - compositionEnd.current < 90 || busy) { e.preventDefault(); e.stopPropagation(); } }}><ArrowUp size={20}/></ComposerPrimitive.Send></div>
  </ComposerPrimitive.Root><p className="composer-note">测量数字仅来自工具结果 · 取消不撤销已执行操作 · 任务按会话隔离</p>{preview && <AttachmentPreview preview={preview} onClose={() => setPreview(undefined)}/>}</div>;
}
