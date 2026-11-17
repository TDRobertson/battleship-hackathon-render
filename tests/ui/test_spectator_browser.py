import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.mark.skipif(not shutil.which("firefox"), reason="Firefox is not installed")
def test_firefox_live_shots_are_sequential_and_refresh_preserves_scroll(tmp_path):
    html = (Path(__file__).resolve().parents[2] / "src/ui/spectator.html").read_text()
    fixture = '''<script>
const nativeFetch = window.fetch.bind(window);
const shot = (player, row, col) => ({player, row, col, outcome:'miss', sunk_cells:[]});
const one = {id:'m1',match_id:'game-1',game:1,bot_a:'Alice',bot_b:'Bob',status:'playing',rows:10,cols:10,shots:[],live_ships_visible:true,fleets:{A:[[3,3]],B:[[4,4]]}};
const two = {id:'m2',match_id:'game-2',game:2,bot_a:'Alice',bot_b:'Bob',status:'playing',rows:10,cols:10,shots:[],live_ships_visible:false};
let visible = [one], pollTimes = [];
const tournament = {id:'t',seed:1,status:'running',wave:1,phase:'winners',finalist_id:null,champion_id:null,waiting:null,byes:[],disqualifications:[],
 entrants:{a:{name:'Alice',losses:0},b:{name:'Bob',losses:0}},pairings:[{id:'p',wave:1,bracket:'winners',bot_a:'a',bot_b:'b',
 status:'playing',games:5,completed:0,a_wins:0,b_wins:0,winner:null,loser:null,rounds:[{id:'m1',game:1,status:'playing'}]}]};
window.fetch = async (url, options) => {
 if (String(url).includes('/api/spectator/matches')) { pollTimes.push(performance.now()); return {ok:true,json:async()=>JSON.parse(JSON.stringify({matches:visible}))}; }
 if (String(url).includes('/api/spectator/tournaments')) return {ok:true,json:async()=>JSON.parse(JSON.stringify({tournaments:[tournament],server_time:Date.now()/1000}))};
 return nativeFetch(url, options);
};
</script>'''
    script = r'''<script>
const observed = [];
let initialScroll, initialBoard, recorded = '';
const observer = new MutationObserver(() => {
 const label = document.querySelector('#turn').textContent;
 const key = selected + ':' + label;
 if (key !== recorded) { recorded = key; observed.push({id:selected, label, at:performance.now()}); }
});
observer.observe(document.querySelector('#turn'), {childList:true,subtree:true,characterData:true});
setTimeout(() => { const card=document.querySelector('.pair'); card.click(); document.querySelector('.pair').focus({preventScroll:true}); }, 400);
setTimeout(() => {
 initialBoard = document.querySelector('.board .grid');
 window.liveShipsVisible = boardViews.A.cells[4][4].classList.contains('ship') && boardViews.B.cells[3][3].classList.contains('ship');
 const ships = document.querySelector('#ships');
 ships.click();
 window.toggledOff = !boardViews.A.cells[4][4].classList.contains('ship') && !boardViews.B.cells[3][3].classList.contains('ship') && ships.textContent==='Show ships';
 ships.click();
 window.toggledOn = boardViews.A.cells[4][4].classList.contains('ship') && boardViews.B.cells[3][3].classList.contains('ship') && ships.textContent==='Hide ships';
 window.preferenceSaved = localStorage.getItem('battleship-show-ships')==='true';
 window.scrollTo(0, document.querySelector('#boards').offsetTop - 100);
 initialScroll = window.scrollY;
 ships.click(); ships.click();
 window.toggleScrollStable = window.scrollY===initialScroll;
}, 800);
setTimeout(() => { one.shots=[shot('A',0,0),shot('B',0,1),shot('A',0,2)]; tournament.pairings[0].a_wins=1; }, 1000);
setTimeout(() => {
 one.status='finished'; one.winner='A'; one.reason='test'; one.fleets={};
 two.shots=[{...shot('A',1,0),outcome:'hit'},shot('B',1,1)]; visible=[two,one];
 tournament.pairings[0].rounds=[{id:'m1',game:1,status:'finished',winner:'a'},{id:'m2',game:2,status:'playing'}];
}, 1320);
function checkShots() {
 const marks = observed.filter(item => /^([123]) \/ (3|2)$/.test(item.label));
 const first = marks.filter(item => item.id==='m1');
 const second = marks.filter(item => item.id==='m2');
 if ((first.length<3 || second.length<2) && performance.now()<9000) { setTimeout(checkShots, 100); return; }
 window.checks = {
  first:first.map(item=>item.label).join('|')==='1 / 3|2 / 3|3 / 3',
  second:second.map(item=>item.label).join('|')==='1 / 2|2 / 2',
  timing:first.length===3 && second.length===2 && first[1].at-first[0].at>=440 && first[2].at-first[1].at>=440 && second[0].at-first[2].at>=440 && second[1].at-second[0].at>=440,
  polling:pollTimes.length>=6 && pollTimes.slice(3,6).every((at, i) => at-pollTimes[i+2]>=440 && at-pollTimes[i+2]<1200),
  stableBoard:initialBoard && initialBoard===document.querySelector('.board .grid'),
  shipsVisible:window.liveShipsVisible,
  toggledOff:window.toggledOff,
  toggledOn:window.toggledOn,
  preferenceSaved:window.preferenceSaved,
  toggleScrollStable:window.toggleScrollStable,
  shipsHidden:!boardViews.A.cells[4][4].classList.contains('ship') && !boardViews.B.cells[3][3].classList.contains('ship'),
  hostLock:document.querySelector('#ships').disabled && document.querySelector('#ships').textContent==='Ships hidden by host',
  scroll:initialScroll>0 && Math.abs(window.scrollY-initialScroll)<5,
  focus:document.activeElement?.dataset?.pairId==='p',
 };
 document.querySelector('#ships').click();
 checks.hostCannotOverride = localStorage.getItem('battleship-show-ships')==='true' && !boardViews.A.cells[4][4].classList.contains('ship');
 const select=document.querySelector('#matches'); select.value='m1'; select.dispatchEvent(new Event('change'));
 const range=document.querySelector('#position'); range.value='0'; range.dispatchEvent(new Event('input'));
 setTimeout(() => {
   checks.manual = selected==='m1' && document.querySelector('#turn').textContent==='0 / 3';
   document.querySelector('#live').click();
   checks.live = selected==='m2' && document.querySelector('#turn').textContent==='2 / 2';
   two.status='finished'; two.winner='B'; two.reason='test'; two.fleets={A:[[3,3]],B:[[4,4]]};
   setTimeout(() => {
     checks.shipsRevealedAfter = boardViews.A.cells[4][4].classList.contains('ship') && boardViews.B.cells[3][3].classList.contains('ship');
     const ships = document.querySelector('#ships');
     checks.toggleEnabledAfter = !ships.disabled;
     ships.click();
     checks.hiddenAfter = !boardViews.A.cells[4][4].classList.contains('ship') && localStorage.getItem('battleship-show-ships')==='false';
     checks.hitsRemainVisible = boardViews.A.cells[1][0].classList.contains('hit');
     ships.click();
     checks.shownAfter = boardViews.A.cells[4][4].classList.contains('ship') && ships.getAttribute('aria-pressed')==='true';
     const replayStarted=performance.now();
     document.querySelector('#replay').click();
     setTimeout(() => {
       const replayShots=observed.filter(item => item.id==='m2' && item.at>=replayStarted && /^(1|2) \/ 2$/.test(item.label));
       checks.replayTiming=replayShots.length===2 && replayShots[0].label==='1 / 2' && replayShots[1].label==='2 / 2' && replayShots[0].at-replayStarted>=440 && replayShots[1].at-replayShots[0].at>=440;
       nativeFetch('/report', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({checks, observed, initialScroll, scrollY:window.scrollY, pollTimes})});
     }, 1300);
   }, 600);
 }, 600);
}
setTimeout(checkShots, 2700);
</script>'''
    html = html.replace('<script>', fixture + '<script>', 1).replace('</body>', script + '</body>')
    report, received = [], threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            report.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()
            received.set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    profile = tmp_path / "firefox-profile"
    profile.mkdir()
    env = {**os.environ, "MOZ_HEADLESS": "1", "MOZ_DISABLE_CONTENT_SANDBOX": "1"}
    browser = subprocess.Popen([shutil.which("firefox"), "--headless", "--no-remote", "--profile", str(profile),
                                f"http://127.0.0.1:{server.server_port}/"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        assert received.wait(20), "Firefox did not complete the spectator test"
        assert all(report[0]["checks"].values()), report[0]
    finally:
        browser.terminate()
        try:
            browser.wait(timeout=5)
        except subprocess.TimeoutExpired:
            browser.kill()
            browser.wait(timeout=5)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
