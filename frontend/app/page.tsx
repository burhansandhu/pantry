"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowDownToLine, ArrowRight, Check, ChefHat, ChevronRight, CircleCheck, Clipboard, CookingPot, Leaf, LoaderCircle, Plus, RotateCcw, ShieldCheck, Sparkles, Sprout, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { readEvents } from "@/lib/stream";
import { splitItems } from "@/lib/ingredients";

type Proposal = { ingredient: string; replacement: string; reason: string; potential_allergens: string[]; required: boolean };
type Review = { review_id: string; kind: "combination" | "substitutions" | "confirmation" | "blocked"; message: string; ingredients: string[]; preferences: string; allergies: string[]; substitution_requests?: string[]; substitutions?: Proposal[] };
type Decision = { accept: boolean; allergy_confirmed: boolean };
const API = process.env.NEXT_PUBLIC_API_URL || "";

function Bowl() {
  return <svg className="bowl-art" viewBox="0 0 260 160" fill="none" aria-hidden="true"><ellipse cx="131" cy="106" rx="89" ry="14" fill="#e6e8d8"/><path d="M47 94h169c-8 39-35 53-84 53s-75-14-85-53Z" fill="#e2e8d8" stroke="#375342" strokeWidth="2"/><path d="M41 91c0-10 41-18 91-18s91 8 91 18-41 17-91 17-91-7-91-17Z" fill="#f5f3e9" stroke="#375342" strokeWidth="2"/><path d="M65 83c8-19 24-25 38-6M95 89c-5-27 14-38 33-21M132 83c3-27 26-34 40-10M169 86c12-21 30-13 34 1" fill="#a7bb8e" stroke="#375342" strokeWidth="2"/><path d="m140 87 51-66M153 90l52-65" stroke="#9a784f" strokeWidth="5" strokeLinecap="round"/><path d="M79 46c0-14 15-17 16-32M118 39c0-10 10-14 11-23" stroke="#9aab8e" strokeWidth="2" strokeLinecap="round"/><circle cx="62" cy="33" r="3" fill="#c4a16a"/><path d="m222 50 4 8 8 4-8 4-4 8-4-8-8-4 8-4 4-8Z" fill="#b89a66"/></svg>;
}

export default function Home() {
  const [ingredients, setIngredients] = useState("");
  const [preferences, setPreferences] = useState("");
  const [allergies, setAllergies] = useState("");
  const [substitutionRequests, setSubstitutionRequests] = useState<string[]>([]);
  const [session, setSession] = useState<string | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [recipe, setRecipe] = useState("");
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState("");
  const [statuses, setStatuses] = useState<string[]>([]);
  const [finalIngredients, setFinalIngredients] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);
  const [about, setAbout] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const ingredientRef = useRef<HTMLTextAreaElement>(null);
  const resultRef = useRef<HTMLElement>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Restore a paused review or a finished recipe after a page refresh.
  useEffect(() => {
    const saved = sessionStorage.getItem("pantry-session");
    if (!saved) return;
    const controller = new AbortController();
    fetch(`${API}/api/sessions/${saved}`, { signal: controller.signal }).then(async res => {
      if (!res.ok) { sessionStorage.removeItem("pantry-session"); return; }
      const state = await res.json();
      setSession(saved); setRecipe(state.recipe); setComplete(Boolean(state.recipe));
      setFinalIngredients(state.ingredients); setIngredients(state.ingredients.join(", "));
      setPreferences(state.preferences || ""); setAllergies((state.allergies || []).join(", "));
      setSubstitutionRequests(state.substitution_requests || []);
      if (state.review) applyReview(state.review);
      if (state.error || state.busy) setError(state.error || "Your previous request is still processing. Refresh shortly to retrieve the result.");
    }).catch(() => {}).finally(() => {});
    return () => controller.abort();
  }, []);

  function applyReview(next: Review) {
    setReview(next); setEditing(false); setDecisions({});
    setIngredients(next.ingredients.join(", ")); setPreferences(next.preferences); setAllergies(next.allergies.join(", "));
    setSubstitutionRequests(next.substitution_requests || []);
    setFinalIngredients(next.ingredients);
  }

  async function request(path: string, payload: unknown) {
    if (busy) return;
    setBusy(true); setError(""); setCopied(false);
    const controller = new AbortController(); abortRef.current = controller;
    let receivedReview = false;
    try {
      const response = await fetch(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: controller.signal });
      await readEvents(response, event => {
        switch (event.type) {
          case "session": setSession(event.session_id as string); sessionStorage.setItem("pantry-session", event.session_id as string); break;
          case "status": setReview(null); setStatuses(prev => [...prev, event.message as string]); break;
          case "review": receivedReview = true; applyReview(event.review as Review); break;
          case "token": setReview(null); setRecipe(prev => prev + (event.text as string)); break;
          case "done": setReview(null); setRecipe(event.recipe as string); setFinalIngredients(event.ingredients as string[]); setComplete(true); break;
          case "error": setReview(null); throw new Error(event.message as string);
        }
      });
      if (receivedReview && window.innerWidth < 900) resultRef.current?.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) setError(err instanceof Error ? err.message : "Could not reach the kitchen. Make sure the backend is running.");
    } finally {
      if (abortRef.current === controller) { setBusy(false); abortRef.current = null; }
    }
  }

  function reset() {
    abortRef.current?.abort(); abortRef.current = null;
    sessionStorage.removeItem("pantry-session");
    setSession(null); setReview(null); setRecipe(""); setComplete(false); setBusy(false); setEditing(false);
    setStatuses([]); setError(""); setDecisions({}); setFinalIngredients([]); setCopied(false);
    setSubstitutionRequests([]);
    ingredientRef.current?.focus();
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const payload = { ingredients: pantryItems, preferences: preferences.trim(), allergies: splitItems(allergies), substitution_requests: requestedSwaps };
    if (!payload.ingredients.length) { setError("Add at least one ingredient to get started."); return; }
    if (editing && review && session) {
      void request(`/api/sessions/${session}/respond`, { review_id: review.review_id, action: "edit", revision: payload });
    } else {
      setRecipe(""); setComplete(false); setStatuses([]);
      void request("/api/sessions", payload);
    }
  }

  function respond(action: string) {
    if (!review || !session) return;
    void request(`/api/sessions/${session}/respond`, { review_id: review.review_id, action,
      decisions: action === "substitutions" ? review.substitutions?.map(p => ({ ingredient: p.ingredient, ...decisions[p.ingredient] })) : [] });
  }

  function edit() {
    setEditing(true); ingredientRef.current?.focus(); ingredientRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const locked = busy || Boolean(session && !editing);
  const pantryItems = splitItems(ingredients);
  const requestedSwaps = pantryItems.filter(item => substitutionRequests.includes(item.toLowerCase()));
  const reviewedAll = review?.substitutions?.every(p => {
    const d = decisions[p.ingredient];
    return d && (d.accept ? d.allergy_confirmed : !p.required);
  });
  const step = recipe || complete ? 3 : review?.kind === "confirmation" ? 2 : review || busy ? 1 : 0;

  return <>
    <header className="topbar"><a href="/" className="brand"><span className="brand-icon"><Sprout size={23}/></span>pantry<span className="brand-dot">.</span></a><span className="top-tag">A little inspiration. A good meal.</span><button className="text-button" onClick={() => setAbout(true)}>How it works <ChevronRight size={15}/></button></header>
    <main className="shell">
      <section className="intro"><div><span className="eyebrow"><span/> YOUR EVERYDAY KITCHEN COMPANION</span><h1>Something good from<br/>what you’ve <em>got.</em></h1><p>A few ingredients, a little guidance, and a recipe that’s yours.<br className="desktop-break"/> Let’s see what’s cooking.</p></div><Bowl/></section>
      <div className="workspace-header"><div className="section-label"><CookingPot size={18}/> The kitchen <span className="small-tag">PERSONALIZED FOR YOU</span></div><button className="text-button" onClick={reset} disabled={busy}><Plus size={15}/> New recipe</button></div>
      <div className="workspace">
        <aside className="pantry-panel">
          <div className="panel-heading"><span className="icon-tile"><Leaf size={19}/></span><div><h2>Your ingredients</h2><p>Start with what’s in your kitchen.</p></div></div>
          <form onSubmit={submit}>
            <label htmlFor="ingredients">What do you have? <span className="required-mark">*</span></label>
            <textarea id="ingredients" ref={ingredientRef} value={ingredients} onChange={e => setIngredients(e.target.value)} placeholder={"e.g. tomatoes, pasta, garlic, basil"} required maxLength={4800} disabled={locked} rows={4}/>
            <p className="field-hint">Separate ingredients with commas or new lines.</p>
            <fieldset className="swap-picker" disabled={locked}>
              <legend>Find substitutes <span className="optional">optional</span></legend>
              <p className="field-hint" id="swap-help">Select ingredients to replace. I’ll suggest alternatives for you to review.</p>
              {pantryItems.length ? <div className="swap-picker-options">{pantryItems.map(item => <label key={item} className={requestedSwaps.includes(item) ? "picked" : ""}><input type="checkbox" aria-describedby="swap-help" checked={requestedSwaps.includes(item)} onChange={e => setSubstitutionRequests(prev => e.target.checked ? [...new Set([...prev, item.toLowerCase()])] : prev.filter(value => value !== item.toLowerCase()))}/><span>{item}</span></label>)}</div> : <p className="swap-empty">Add your ingredients above to choose which ones to replace.</p>}
            </fieldset>
            <label htmlFor="preferences">Make it your own <span className="optional">optional</span></label>
            <textarea id="preferences" value={preferences} onChange={e => setPreferences(e.target.value)} placeholder="A quick dinner? Vegetarian? Something spicy?" rows={2} maxLength={2000} disabled={locked}/>
            <label htmlFor="allergies" className="allergy-label"><ShieldCheck size={15}/> Any allergies? <span className="optional">optional</span></label>
            <input id="allergies" value={allergies} onChange={e => setAllergies(e.target.value)} placeholder="e.g. peanuts, dairy, sesame" maxLength={3600} disabled={locked}/>
            <p className="field-hint">We’ll consider these before suggesting swaps.</p>
            <button className="primary-button full" disabled={locked || !ingredients.trim()}>{busy ? <><LoaderCircle className="spin" size={17}/> Working on it</> : <>{editing ? "Recheck ingredients" : "Find my recipe"}<ArrowRight size={17}/></>}</button>
          </form>
          <div className="panel-note"><Sparkles size={17}/><p>Thoughtful pairings. Useful swaps.<br/>You have the final say.</p></div>
        </aside>
        <section className="chef-panel" ref={resultRef} aria-label="Recipe assistant">
          <div className="chef-heading"><div className="chef-avatar"><ChefHat size={22}/></div><div><h2>Your kitchen assistant</h2><p>{busy ? "A little kitchen magic in progress" : complete ? "Made just for you" : "Ready when you are"}</p></div><span className={`availability ${busy ? "working" : ""}`}><span/>{busy ? "Thinking" : "Here to help"}</span></div>
          <div className="steps">{["Ingredients", "Review & swaps", "Your approval", "Let’s cook"].map((label, index) => <div className={index === step ? "active" : index < step ? "passed" : ""} key={label}><span>{index < step ? <Check size={12}/> : index + 1}</span>{label}</div>)}</div>
          <div className="conversation">
            {!session && !busy && !error && <div className="empty-state"><div className="empty-icon"><CookingPot size={38} strokeWidth={1.3}/><span><Sparkles size={17}/></span></div><span className="eyebrow">GOOD FOOD STARTS HERE</span><h3>What’s in your pantry?</h3><p>Tell me what you have. I’ll check what works together,<br className="desktop-break"/> suggest helpful swaps, and turn it into something delicious.</p><div className="starter-label">NEED A LITTLE INSPIRATION?</div><div className="starters">{[{label:"A quick pasta",items:"pasta, tomatoes, garlic, olive oil",pref:"A quick dinner in under 30 minutes"},{label:"A cozy bowl",items:"rice, carrots, chickpeas, spinach",pref:"A comforting vegetarian bowl"},{label:"Use my leftovers",items:"cooked rice, eggs, peas, soy sauce",pref:"Use up leftovers"}].map(s => <button key={s.label} onClick={() => { setIngredients(s.items); setPreferences(s.pref); ingredientRef.current?.focus(); }}>{s.label}<ArrowRight size={13}/></button>)}</div></div>}
            {statuses.length > 0 && <div className="activity" aria-live="polite">{statuses.map((status, i) => <div key={i}>{busy && i === statuses.length - 1 ? <LoaderCircle className="spin" size={14}/> : <CircleCheck size={14}/>}<span>{status}</span></div>)}</div>}
            {review && !editing && <div className="review-card">
              <span className="card-kicker">{review.kind === "confirmation" ? "ONE LAST CHECK" : review.kind === "substitutions" ? "A THOUGHTFUL SWAP" : "LET’S CHECK IN"}</span>
              <h3>{review.kind === "combination" ? "An adventurous combination" : review.kind === "substitutions" ? "A few ingredient adjustments" : review.kind === "blocked" ? "Let’s revise these ingredients" : "Ready to make something good?"}</h3>
              <p>{review.message}</p>
              {review.kind === "substitutions" && review.substitutions?.map(p => {
                const d = decisions[p.ingredient];
                return <div className="substitute" key={p.ingredient}><div className="swap-names"><span>{p.ingredient}</span><ArrowRight size={16}/><strong>{p.replacement}</strong>{p.required && <span className="required-tag">Required</span>}</div><p>{p.reason}</p><div className="allergen-note"><ShieldCheck size={14}/>{p.potential_allergens.length ? `Potential allergens: ${p.potential_allergens.join(", ")}` : "No specific allergens identified by the model. Check the label."}</div><div className="swap-choices"><button className={d?.accept ? "selected" : ""} onClick={() => setDecisions(prev => ({...prev, [p.ingredient]: {accept: true, allergy_confirmed: false}}))} disabled={busy}>Use this swap</button><button className={d && !d.accept ? "selected" : ""} onClick={() => setDecisions(prev => ({...prev, [p.ingredient]: {accept: false, allergy_confirmed: false}}))} disabled={busy}>{p.required ? "I can’t use this" : "Keep original"}</button></div>{d?.accept && <label className="checkbox-label"><input type="checkbox" checked={d.allergy_confirmed} onChange={e => setDecisions(prev => ({...prev, [p.ingredient]: {...d, allergy_confirmed: e.target.checked}}))} disabled={busy}/><span>I have no known allergy to <strong>{p.replacement}</strong> and have checked its ingredients.</span></label>}{d && !d.accept && p.required && <p className="inline-warning">Edit your ingredients or allergy information to choose a different option.</p>}</div>;
              })}
              {review.kind === "confirmation" && <><div className="ingredient-chips">{review.ingredients.map(item => <span key={item}><Check size={12}/>{item}</span>)}</div><dl className="review-details"><div><dt>Preferences</dt><dd>{review.preferences || "Anything delicious"}</dd></div><div><dt>Allergies</dt><dd>{review.allergies.join(", ") || "None declared"}</dd></div></dl><p className="safety-note">Check product labels and cross-contact information for your allergies.</p></>}
              <div className="card-actions">{review.kind !== "blocked" && <button className="primary-button" disabled={busy || (review.kind === "substitutions" && !reviewedAll)} onClick={() => respond(review.kind === "combination" ? "keep" : review.kind === "substitutions" ? "substitutions" : "generate")}>{review.kind === "combination" ? "Keep this combination" : review.kind === "substitutions" ? "Confirm my choices" : "Generate my recipe"}<ArrowRight size={16}/></button>}<button className="secondary-button" onClick={edit} disabled={busy}>Edit ingredients</button></div>
            </div>}
            {editing && <div className="edit-note"><RotateCcw size={18}/><p>Make your changes in the ingredient form, then select <strong>Recheck ingredients</strong>.</p><button className="text-button" onClick={() => { applyReview(review!); }}>Cancel</button></div>}
            {recipe && <article className={`recipe-output ${!complete ? "streaming" : ""}`}><div className="recipe-meta"><span className="card-kicker">{complete ? "YOUR PERSONALIZED RECIPE" : "FRESH FROM THE KITCHEN"}</span>{complete && <div className="recipe-tools"><button aria-label="Copy recipe" title="Copy recipe" onClick={async () => { try { await navigator.clipboard.writeText(recipe); setCopied(true); } catch { setError("Copy failed. You can download the recipe instead."); } }}>{copied ? <Check size={17}/> : <Clipboard size={17}/>}</button><button aria-label="Download recipe" title="Download recipe" onClick={() => { const url = URL.createObjectURL(new Blob([recipe], {type:"text/markdown;charset=utf-8"})); const a = document.createElement("a"); a.href = url; a.download = "my-pantry-recipe.md"; a.click(); URL.revokeObjectURL(url); }}><ArrowDownToLine size={17}/></button></div>}</div><div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{recipe}</ReactMarkdown>{!complete && busy && <span className="writing-cursor"/>}</div>{complete && <div className="recipe-end"><CircleCheck size={17}/><span>Made with {finalIngredients.length} approved ingredients. Enjoy every bite.</span></div>}</article>}
            {error && <div className="error-box" role="alert"><p>{error}</p><button className="secondary-button" onClick={reset}><RotateCcw size={14}/> Start again</button></div>}
            {busy && !recipe && <div className="thinking"><span/><span/><span/><span className="thinking-text">A little thought before we cook.</span></div>}
          </div>
          <div className="chef-footer"><ShieldCheck size={14}/><span>Swaps are always reviewed by you before cooking begins.</span></div>
        </section>
      </div>
      <footer className="page-footer"><span>Less waste. More possibility.</span><span>Made for your everyday kitchen <Sprout size={14}/></span></footer>
    </main>
    {about && <div className="modal-backdrop" onClick={() => setAbout(false)}><section className="about-modal" role="dialog" aria-modal="true" aria-label="How Pantry works" onClick={e => e.stopPropagation()}><button className="close-button" aria-label="Close" onClick={() => setAbout(false)}><X size={20}/></button><span className="eyebrow">A LITTLE GUIDANCE</span><h2>From pantry to plate.</h2><ol><li>Add your ingredients, preferences and known allergies.</li><li>Your assistant assesses pairings and suggests useful replacements.</li><li>Review unusual pairings and confirm allergy suitability for each accepted swap.</li><li>Approve your final ingredients and watch your recipe come together.</li></ol><p>Suggestions come from an AI model. Always check ingredient labels and cross-contact information when managing allergies.</p><button className="primary-button" onClick={() => setAbout(false)}>Let’s get cooking <ArrowRight size={16}/></button></section></div>}
  </>;
}
