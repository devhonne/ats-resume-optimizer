import { Icon } from "./Icons";

interface Props {
  prompt: string; aiReady: boolean; aiNote: string; tailoring: boolean; state: string;
  onCopy: () => void; onPaste: () => void; onTailor: () => void;
}

export function EnhanceCard({ prompt, aiReady, aiNote, tailoring, state, onCopy, onPaste, onTailor }: Props) {
  return (
    <section className={`card ${state}`} aria-labelledby="h-enh">
      <div className="ch"><span className="no">4</span><h2 id="h-enh">Enhance your resume</h2></div>
      <div className="promise"><Icon name="shield" /><span>Your skills stay. Tailoring only reorders and rewords what's already in your resume. Every result is checked, and anything removed is flagged and can be restored.</span></div>
      <div className="lockable" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <ol className="how">
          <li><b>Copy the prompt.</b> It contains your resume, the job, and the gaps.</li>
          <li>Paste it into <b>Claude</b> or <b>ChatGPT</b> and send.</li>
          <li>Copy the whole reply → <b>Paste AI reply</b>. Review it on the right.</li>
        </ol>
        <textarea id="prompt" readOnly value={prompt} aria-label="Prompt for Claude or ChatGPT" placeholder="Your prompt appears here after the ATS check." />
        <div className="row">
          <button className="btn sun" onClick={onCopy}><Icon name="copy" />Copy prompt</button>
          <a className="btn" href="https://claude.ai/new" target="_blank" rel="noreferrer"><Icon name="ext" />Claude</a>
          <a className="btn" href="https://chatgpt.com/" target="_blank" rel="noreferrer"><Icon name="ext" />ChatGPT</a>
          <button className="btn" onClick={onPaste}><Icon name="inbox" />Paste AI reply</button>
        </div>
        <div className="or">or let Gemini do it here</div>
        <div className="row" style={{ alignItems: "center" }}>
          <button className="btn ink" onClick={onTailor} disabled={tailoring || !aiReady}><Icon name="zap" />{tailoring ? "Tailoring…" : "Auto-tailor with Gemini"}</button>
          <span className="help">{aiNote}</span>
        </div>
      </div>
    </section>
  );
}
