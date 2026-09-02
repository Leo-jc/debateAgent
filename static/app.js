/* 辩论场前端：EventSource 收 SSE，渲染对峙线直播 + 战报。 */
(function () {
  "use strict";

  var $topic = document.getElementById("topic");
  var $start = document.getElementById("start");
  var $status = document.getElementById("status");
  var $errbar = document.getElementById("errbar");
  var $arena = document.getElementById("arena");
  var $stream = document.getElementById("stream");
  var $report = document.getElementById("report");
  var $reportBody = document.getElementById("reportBody");
  var $endReason = document.getElementById("endReason");
  var $download = document.getElementById("download");

  var debateId = null;
  var currentCard = null;      // 正在流式的发言卡
  var pendingText = [];        // rAF 批量追加缓冲
  var rafScheduled = false;
  var autoScroll = true;
  var reportText = "";

  // ── 滚动跟随：用户上滚暂停，回底恢复 ──
  window.addEventListener("scroll", function () {
    autoScroll = window.innerHeight + window.scrollY >= document.body.scrollHeight - 80;
  });
  function scrollToBottom() {
    if (autoScroll) window.scrollTo(0, document.body.scrollHeight);
  }

  // ── rAF 批量打字机 ──
  function queueDelta(text) {
    pendingText.push(text);
    if (!rafScheduled) {
      rafScheduled = true;
      requestAnimationFrame(flushDelta);
    }
  }
  function flushDelta() {
    rafScheduled = false;
    if (currentCard && pendingText.length) {
      currentCard.querySelector(".speech").append(pendingText.join(""));
      pendingText = [];
      scrollToBottom();
    }
  }

  function el(html) {
    var d = document.createElement("div");
    d.innerHTML = html.trim();
    return d.firstChild;
  }
  function sideName(side) { return side === "pro" ? "正方" : "反方"; }

  function speechStart(side, round) {
    flushDelta();
    currentCard = el(
      '<div class="card ' + side + '"><div class="tag">【第 ' + round + " 轮 · " +
      sideName(side) + "】</div><div class=\"speech\"><span class='cursor'></span></div></div>"
    );
    $stream.appendChild(currentCard);
    scrollToBottom();
  }
  function speechEnd() {
    flushDelta();
    if (currentCard) {
      var c = currentCard.querySelector(".cursor");
      if (c) c.remove();
    }
    currentCard = null;
  }

  function judgeShow(d) {
    flushDelta();
    speechEnd();
    var st = d.status === "concede"
      ? '<span class="st-concede">认输 · ' + sideName(d.conceded_side) + "方落败</span>"
      : '<span class="st-continue">继续</span>';
    var card = el(
      '<div class="card judge-card"><div class="tag">⚖ 第 ' + d.round + " 轮 · 裁判判定</div>" +
      '<div class="verdict">' + st + "</div><div>" + d.reason + "</div></div>"
    );
    if (d.status === "concede") {
      card.appendChild(el('<div class="stamp s-' + d.conceded_side + '">负</div>'));
    }
    $stream.appendChild(card);
    scrollToBottom();
  }

  function doneShow(d) {
    speechEnd();
    reportText = d.report || "";
    $endReason.textContent = d.end_reason || "";
    $reportBody.textContent = reportText;
    $report.classList.add("show");
    $status.textContent = "";
    $start.disabled = false;
    $topic.disabled = false;
    scrollToBottom();
  }

  function showError(msg) {
    $errbar.textContent = msg;
    $errbar.style.display = "block";
    $status.innerHTML = "";
    $start.disabled = false;
    $topic.disabled = false;
    if (currentCard) currentCard.querySelector(".cursor").remove();
    currentCard = null;
  }

  var handlers = {
    split_done: function (d) {
      document.getElementById("splitBar").style.visibility = "visible";
      document.getElementById("posPro").textContent = d.pro;
      document.getElementById("posCon").textContent = d.con;
    },
    speech_start: function (d) { speechStart(d.side, d.round); },
    speech_delta: function (d) { queueDelta(d.text); },
    speech_end: function () { speechEnd(); },
    judge: judgeShow,
    done: doneShow,
    error: function (d) { showError(d.message); }
  };

  function listen(id) {
    var es = new EventSource("/api/stream/" + id);
    Object.keys(handlers).forEach(function (type) {
      es.addEventListener(type, function (e) {
        handlers[type](JSON.parse(e.data));
        if (type === "done" || type === "error") es.close();
      });
    });
    es.onerror = function () {
      // EventSource 原生自动重连；若辩论已结束（404/关闭）则停止
      if (es.readyState === EventSource.CLOSED) es.close();
    };
  }

  $start.addEventListener("click", function () {
    var topic = $topic.value.trim();
    if (!topic) { showError("请输入辩题"); return; }
    $errbar.style.display = "none";
    $start.disabled = true;
    $topic.disabled = true;
    $status.innerHTML = '<span class="dot"></span>拆题中…';
    $stream.innerHTML = "";
    $report.classList.remove("show");
    autoScroll = true;

    fetch("/api/debate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: topic })
    }).then(function (r) {
      if (r.status === 409) throw new Error("已有辩论进行中，请等待完成或刷新页面");
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || "发起失败"); });
      return r.json();
    }).then(function (j) {
      debateId = j.debate_id;
      $status.innerHTML = '<span class="dot"></span>辩论进行中…';
      $arena.classList.add("live");
      listen(debateId);
    }).catch(function (err) {
      showError(err.message);
    });
  });

  $download.addEventListener("click", function () {
    var blob = new Blob([reportText], { type: "text/markdown" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "debate-report.md";
    a.click();
    URL.revokeObjectURL(a.href);
  });
})();
