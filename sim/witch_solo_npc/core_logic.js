const MAT=[{name:"満月草",icon:"🌙",color:"var(--m0)"},{name:"火竜の鱗",icon:"🔥",color:"var(--m1)"},{name:"影茸",icon:"🍄",color:"var(--m2)"},{name:"星屑",icon:"✨",color:"var(--m3)"},{name:"霜結晶",icon:"❄️",color:"var(--m4)"},{name:"蛇毒",icon:"🐍",color:"var(--m5)"}];
const POOL=[
 {id:"pair_満星",type:"pair",a:0,b:3,pt:4},{id:"pair_火霜",type:"pair",a:1,b:4,pt:4},{id:"pair_影蛇",type:"pair",a:2,b:5,pt:4},
 {id:"pair_満火",type:"pair",a:0,b:1,pt:4},{id:"pair_星影",type:"pair",a:3,b:2,pt:4},{id:"pair_霜蛇",type:"pair",a:4,b:5,pt:4},
 {id:"cnt2_満火",type:"cnt2",a:0,b:1,pt:5},{id:"cnt2_影星",type:"cnt2",a:2,b:3,pt:5},{id:"cnt2_霜蛇",type:"cnt2",a:4,b:5,pt:5},{id:"cnt2_満霜",type:"cnt2",a:0,b:4,pt:5},
 {id:"solo_星",type:"solo",a:3,pt:3},{id:"solo_霜",type:"solo",a:4,pt:3},{id:"solo_満",type:"solo",a:0,pt:3},{id:"solo_火",type:"solo",a:1,pt:3},
 {id:"abs2_影蛇",type:"abs2",a:2,b:5,pt:3},{id:"abs2_火星",type:"abs2",a:1,b:3,pt:3},
 {id:"abs_影",type:"abs",a:2,pt:2},{id:"abs_蛇",type:"abs",a:5,pt:2}];
const byId=id=>POOL.find(r=>r.id===id);
const TYPE={pair:{jp:"同居",icon:"🤝"},cnt2:{jp:"個数",icon:"🔢"},solo:{jp:"単体",icon:"1️⃣"},abs2:{jp:"二種忌避",icon:"⛔"},abs:{jp:"忌避",icon:"🚫"},hard:{jp:"秘伝",icon:"🌟"}};
// 上級モードの高難度枠（「Xを2つ以上、Yを入れない」複合・+10・達成率35%前後で均一）
const HARD=[
 {id:"H_火2蛇無",type:"hard",a:1,b:5,pt:10},{id:"H_影2満無",type:"hard",a:2,b:0,pt:10},{id:"H_星2霜無",type:"hard",a:3,b:4,pt:10},
 {id:"H_霜2影無",type:"hard",a:4,b:2,pt:10},{id:"H_満2星無",type:"hard",a:0,b:3,pt:10},{id:"H_蛇2火無",type:"hard",a:5,b:1,pt:10}];
const byIdAny=id=>POOL.find(r=>r.id===id)||HARD.find(r=>r.id===id);
function recipeMats(r){return (r.type==="pair"||r.type==="cnt2"||r.type==="abs2"||r.type==="hard")?[r.a,r.b]:[r.a];}
function recipeText(r){const m=i=>`${MAT[i].icon}${MAT[i].name}`;
  if(r.type==="pair")return `${m(r.a)} と ${m(r.b)} を同じ坩堝に`;
  if(r.type==="cnt2")return `${m(r.a)} を2つ以上、または ${m(r.b)} を2つ以上`;
  if(r.type==="solo")return `${m(r.a)} をちょうど1つ`;
  if(r.type==="abs2")return `${m(r.a)} と ${m(r.b)} を両方入れない`;
  if(r.type==="hard")return `${m(r.a)} を2つ以上、かつ ${m(r.b)} を入れない`;
  return `${m(r.a)} を入れない`;}
function scoreRecipe(r,pile){const c=x=>pile.filter(m=>m===x).length;
  if(r.type==="pair")return (c(r.a)>=1&&c(r.b)>=1)?r.pt:0;
  if(r.type==="cnt2")return (c(r.a)>=2||c(r.b)>=2)?r.pt:0;
  if(r.type==="solo")return c(r.a)===1?r.pt:0;
  if(r.type==="abs2")return (c(r.a)===0&&c(r.b)===0)?r.pt:0;
  if(r.type==="abs")return c(r.a)===0?r.pt:0;
  if(r.type==="hard")return (c(r.a)>=2&&c(r.b)===0)?r.pt:0;
  return 0;}
function scorePile(rs,p){return rs.reduce((s,r)=>s+scoreRecipe(r,p),0);}
function shuffle(a){a=a.slice();for(let i=a.length-1;i>0;i--){const j=(Math.random()*(i+1))|0;[a[i],a[j]]=[a[j],a[i]];}return a;}
function comb(a,k){const r=[];(function rec(s,c){if(c.length===k){r.push(c.slice());return;}for(let i=s;i<a.length;i++){c.push(a[i]);rec(i+1,c);c.pop();}})(0,[]);return r;}
function permA(a){if(a.length<=1)return[a];const res=[];a.forEach((v,i)=>{const rest=[...a.slice(0,i),...a.slice(i+1)];permA(rest).forEach(p=>res.push([v,...p]));});return res;}
function makeBand(n){const bag=[];for(let m=0;m<6;m++)for(let k=0;k<3;k++)bag.push(m);return shuffle(bag).slice(0,n*3);}
function cutSets(len,nc){return comb([...Array(len-1).keys()].map(i=>i+1),nc);}
function toPiles(b,cs){const s=cs.slice().sort((a,b)=>a-b);const pts=[0,...s,b.length];const pl=[];for(let i=0;i<pts.length-1;i++)pl.push(b.slice(pts[i],pts[i+1]));return pl;}
function E_sb(p){let s=0;for(const r of POOL)s+=scoreRecipe(r,p);return 3*s/POOL.length;}
function dealConflicts(ch){const a=new Set(),w=new Set();for(const i of ch){const r=POOL[i];
  if(r.type==="abs")a.add(r.a); if(r.type==="abs2"){a.add(r.a);a.add(r.b);}
  if(r.type==="pair"||r.type==="cnt2"){w.add(r.a);w.add(r.b);} if(r.type==="solo")w.add(r.a);}
  for(const m of a)if(w.has(m))return true;return false;}
function dealRecipeIds(n){for(let t=0;t<600;t++){const c=shuffle(POOL.map((_,i)=>i)).slice(0,n*3);if(!dealConflicts(c))return Array.from({length:n},(_,p)=>c.slice(p*3,p*3+3).map(i=>POOL[i].id));}const c=shuffle(POOL.map((_,i)=>i)).slice(0,n*3);return Array.from({length:n},(_,p)=>c.slice(p*3,p*3+3).map(i=>POOL[i].id));}
function omniMax(band,players){const n=players.length;let best=-1e9;for(const cs of cutSets(band.length,n-1)){const piles=toPiles(band,cs);for(const pm of permA([...Array(n).keys()])){let t=0;for(let i=0;i<n;i++)t+=scorePile(players[pm[i]],piles[i]);if(t>best)best=t;}}return best;}
// その切り方（cuts）で、全員の好みを見て最適に割り当てたときのチーム点＝切り方そのものの実力
function bestForCut(band,cuts,players){const n=players.length;const piles=toPiles(band,cuts);let best=-1e9;
  for(const pm of permA([...Array(n).keys()])){let t=0;for(let i=0;i<n;i++)t+=scorePile(players[pm[i]],piles[i]);if(t>best)best=t;}
  return best;}
function seenBy(i,j,pl,pile){return i===j?scorePile(pl[j],pile):E_sb(pile);}
function bestAssign(ch,pi,idx,pl){let b=-1e9;for(const P of permA([...Array(idx.length).keys()])){let t=0;for(let k=0;k<idx.length;k++)t+=seenBy(ch,idx[k],pl,pi[P[k]]);if(t>b)b=t;}return b;}
function seqChoose(pi,pl,ct){const n=pl.length;const o=[];for(let i=0;i<n;i++){const x=(ct+1+i)%n;if(x!==ct)o.push(x);}let av=pi.map((p,i)=>({p,i}));const as={};for(let oi=0;oi<o.length;oi++){const me=o[oi];const ot=[...o.slice(oi+1),ct];let bv=-1e9,bp=null;for(const c of av){const rt=av.filter(x=>x.i!==c.i).map(x=>x.p);const lk=rt.length===ot.length?bestAssign(me,rt,ot,pl):0;const v=seenBy(me,me,pl,c.p)+lk;if(v>bv){bv=v;bp=c;}}as[me]=bp;av=av.filter(x=>x.i!==bp.i);}as[ct]=av[0];return as;}
function rationalReach(band,pl,ct){const n=pl.length;let bA=null,bE=-1e9;for(const cs of cutSets(band.length,n-1)){const piles=toPiles(band,cs);const asg=seqChoose(piles,pl,ct);let e=0;for(let i=0;i<n;i++)e+=seenBy(ct,i,pl,asg[i].p);if(e>bE){bE=e;bA=asg;}}let a=0;for(let i=0;i<n;i++)a+=scorePile(pl[i],bA[i].p);return a;}
function chooseOrder(cutter,n){const o=[];for(let i=0;i<n;i++){const idx=(cutter+1+i)%n;if(idx!==cutter)o.push(idx);}return o;}

