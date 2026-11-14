// test_editor.py 가 부른다: node test_editor.js <편집기 주소>
const { chromium } = require("playwright");
const fails = [];
const check = (n, ok, d) => { console.log((ok ? "  통과 " : "  실패 ") + n + (ok ? "" : "  " + d)); if (!ok) fails.push(n); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const br = await chromium.launch(), pg = await br.newPage({ viewport: { width: 1500, height: 900 } });
  const errs = []; pg.on("pageerror", e => errs.push(String(e))); pg.on("dialog", d => d.accept());
  await pg.goto(process.argv[2]); await pg.waitForSelector("#status:has-text('준비됨')");
  const go = async n => { await pg.fill("#pageNo", String(n)); await pg.dispatchEvent("#pageNo", "change"); await sleep(300); };
  await go(3); await pg.click("#chapStart"); await pg.fill("#chapTitle", "1장 시작"); await pg.fill("#chapPage", "1"); await pg.click("#chapOk"); await sleep(300);
  check("글 없는 쪽에서 챕터 시작", (await pg.innerText("#pgFlags")).includes("챕터 시작: 1장 시작"), await pg.innerText("#pgFlags"));
  await go(6); await pg.click("#chapStart"); await pg.fill("#chapTitle", "2장 도구"); await pg.fill("#chapPage", "4"); await pg.selectOption("#chapSplit", "topic"); await pg.click("#chapOk"); await sleep(300);
  await go(7); await pg.click("#pageSkip"); await sleep(300);
  check("이 쪽 빼기 표시", (await pg.innerText("#pgFlags")).includes("뺀 쪽"));
  await go(9); await pg.click("#pageFix"); await pg.fill("#fixPage", "8"); await pg.click("#fixOk"); await sleep(300);
  check("캡처 9 = 책 8P", (await pg.innerText("#edTitle")).includes("책 8P (캡처 9)"), await pg.innerText("#edTitle"));
  await go(4);
  check("캡처 4 = 책 2P", (await pg.innerText("#edTitle")).includes("책 2P (캡처 4)"), await pg.innerText("#edTitle"));
  await go(8);
  await pg.evaluate(() => { ed.value = "…끝난다. 대주제B 첫 문장…"; onEdited(); const a = ed.value.indexOf("대주제B"); ed.focus(); ed.setSelectionRange(a, a + 4); });
  await pg.click("#fH1"); await sleep(300);
  const got = await pg.inputValue("#editor");
  check("고른 글을 제목으로 떼기", got === "…끝난다.\n\n## 대주제B\n\n첫 문장…", JSON.stringify(got));
  await sleep(2200);
  await pg.click("#pageList"); check("쪽 목록 9칸", (await pg.locator(".pchip").count()) === 9, ""); await pg.click("#plClose");
  await pg.click("#tocBtn"); const toc = await pg.innerText("#tocList"); await pg.click("#tocClose");
  check("목차에 챕터·대주제", toc.includes("# 2장 도구") && toc.includes("## 대주제B"), toc);
  await go(3); await pg.click("#pageSkip"); await sleep(400);  // 챕터 시작 쪽도 빼기 → 챕터 설정은 살아 있음
  check("뺀 쪽에도 챕터 표시 유지", (await pg.innerText("#pgFlags")).includes("챕터 시작") && (await pg.innerText("#pgFlags")).includes("뺀 쪽"), await pg.innerText("#pgFlags"));
  await pg.click("#pageSkip"); await sleep(400);
  check("화면 오류 없음", errs.length === 0, errs.join("|"));
  await br.close();
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
