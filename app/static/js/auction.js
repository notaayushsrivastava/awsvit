(() => {
  const boot = document.getElementById("bootstrap");
  const AUCTION_ID = boot.dataset.auctionId;
  const ME = boot.dataset.me || null;
  const fmt = (n) => Number(n).toLocaleString("en-IN");
  const $ = (id) => document.getElementById(id);

  // Motion and confetti arrive from CDNs; degrade to no-op if unavailable.
  const M = window.Motion || null;
  const animate = M ? M.animate : () => {};
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const canAnimate = (fn, ...args) => (!reduced && M ? fn(...args) : undefined);

  const CROWN_SVG =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" class="w-full h-full" aria-hidden="true">' +
    '<path d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L20.819 5.5' +
    'a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.735H6.174a1 1 0 0 1-.957-.735' +
    'L2.383 6.02a.5.5 0 0 1 .798-.519l3.912 3.664a1 1 0 0 0 1.516-.294z"></path>' +
    '<path d="M5 21h14"></path></svg>';

  document.querySelectorAll("[data-crown]").forEach((el) => {
    el.classList.add("inline-block", "w-4", "h-4");
    el.innerHTML = CROWN_SVG;
  });
  const crownLg = document.querySelector("[data-crown-lg]");
  if (crownLg) {
    crownLg.classList.add("inline-block", "w-9", "h-9", "md:w-12", "md:h-12");
    crownLg.innerHTML = CROWN_SVG;
  }

  const socket = io();
  let myLastBidAmount = null;
  let myRequestId = null;
  let lastSeq = Number(boot.dataset.seq);

  // crypto.randomUUID exists only in secure contexts; fall back for plain
  // HTTP / LAN access. Not cryptographic — it's just an idempotency key.
  const uuid = () =>
    crypto.randomUUID
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
          const r = (Math.random() * 16) | 0;
          return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
        });

  /* ------------------------------------------------------------ connection */

  function setConn(connected, label) {
    $("conn-dot").className =
      "w-2 h-2 rounded-full inline-block " +
      (connected ? "bg-pastelgreen-text" : "bg-pastelred-text/60");
    $("conn-label").textContent = label;
  }

  socket.on("connect", () => {
    setConn(true, "connected");
    socket.emit("join_auction", { auction_id: AUCTION_ID });
  });
  socket.on("disconnect", () => setConn(false, "reconnecting"));
  socket.on("reconnect", () => {
    setConn(true, "connected");
    socket.emit("join_auction", { auction_id: AUCTION_ID });
  });
  socket.on("server_error", (d) => toast(d.detail || d.error));

  /* --------------------------------------------------------------- sidebar */

  const sidebar = $("sidebar");
  const toggle = $("sidebar-toggle");
  function setSidebar(open) {
    if (!sidebar) return;
    sidebar.classList.toggle("hidden", !open);
    if (toggle) toggle.setAttribute("aria-expanded", String(open));
  }
  if (toggle)
    toggle.addEventListener("click", () =>
      setSidebar(sidebar.classList.contains("hidden"))
    );
  if ($("sidebar-close"))
    $("sidebar-close").addEventListener("click", () => setSidebar(false));

  /* ----------------------------------------------------------- leaderboard */

  function renderLeaderboard(rows, winner) {
    const list = $("leaderboard");
    if (!list) return;
    const empty = $("leaderboard-empty");
    list.innerHTML = "";
    if (empty) empty.classList.toggle("hidden", rows.length > 0);
    rows.forEach((r) => {
      const isTop = r.rank === 1 && r.top_bid != null;
      const li = document.createElement("li");
      li.className =
        "leaderboard-row flex items-center gap-3 py-3 text-sm" +
        (r.top_bid == null ? " opacity-50" : "");
      li.dataset.bidder = r.bidder;
      li.innerHTML =
        '<span class="w-5 font-mono text-xs text-mute tabular-nums" data-rank>' +
        r.rank +
        "</span>" +
        '<span class="crown inline-block w-4 h-4 text-pastelyellow-text' +
        (isTop ? "" : " hidden") +
        '" data-crown></span>' +
        '<span class="flex-1 truncate"></span>' +
        (r.top_bid == null
          ? '<span class="font-mono text-xs text-mute" data-top-bid>waiting to bid</span>'
          : '<span class="font-mono tabular-nums" data-top-bid>' + fmt(r.top_bid) + "</span>");
      li.children[2].textContent = r.bidder;
      li.querySelector("[data-crown]").innerHTML = CROWN_SVG;
      if (r.bidder === ME) li.classList.add("font-medium");
      if (winner && r.bidder === winner)
        li.querySelector("[data-crown]").classList.remove("hidden");
      list.appendChild(li);
    });
    const count = $("sidebar-count");
    if (count) count.textContent = rows.length;
    canAnimate(() => {
      const items = Array.from(list.children);
      if (items.length)
        animate(
          items,
          { opacity: [0, 1], y: [8, 0] },
          { delay: M.stagger(0.05), duration: 0.35 }
        );
    });
  }

  /* ---------------------------------------------------------------- chat */

  function chatRow(msg) {
    const li = document.createElement("li");
    li.className = "chat-msg";
    li.dataset.bidder = msg.bidder;
    const head = document.createElement("div");
    head.className = "text-xs text-mute font-mono";
    head.textContent = msg.bidder + " · " + String(msg.created_at || "").slice(11, 19);
    const body = document.createElement("div");
    body.className = "mt-0.5 break-words";
    body.textContent = msg.body;
    li.append(head, body);
    return li;
  }

  socket.on("chat_message", ({ message }) => {
    const list = $("chat-list");
    if (!list) return;
    const li = chatRow(message);
    list.appendChild(li);
    list.scrollTop = list.scrollHeight;
    canAnimate(() => animate(li, { opacity: [0, 1], y: [6, 0] }, { duration: 0.3 }));
  });

  if ($("chat-form")) {
    $("chat-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const body = $("chat-input").value.trim();
      if (!body) return;
      socket.emit("send_chat", { auction_id: AUCTION_ID, body });
      $("chat-input").value = "";
    });
  }
  /* --------------------------------------------------------- state + bids */

  function reconcile() {
    socket.emit("request_state", { auction_id: AUCTION_ID });
  }

  socket.on("auction_state", (state) => {
    lastSeq = state.sequence;
    $("current-bid").textContent = fmt(state.current_bid);
    $("min-bid").innerHTML =
      'Minimum valid bid: <span class="tabular-nums">' +
      fmt(state.minimum_valid_bid) +
      "</span>";
    $("amount").value = state.minimum_valid_bid;
    $("amount").min = state.minimum_valid_bid;
    $("auction-status").textContent = state.status;
    if (state.leaderboard) renderLeaderboard(state.leaderboard, state.highest_bidder);
    if (state.status !== "LIVE") {
      $("bid-form").querySelector("button").disabled = true;
      showEndState(state.highest_bidder, state.current_bid, { celebrate: false });
    }
  });

  socket.on("leaderboard_updated", ({ leaderboard }) => {
    renderLeaderboard(leaderboard, boot.dataset.winner || null);
  });

  socket.on("bid_rejected", (d) => {
    myLastBidAmount = null;
    if (d.reason === "BID_TOO_LOW") {
      toast(
        "Bid rejected. Current bid: " + fmt(d.current_bid) +
        ". Minimum valid bid: " + fmt(d.minimum_valid_bid) + "."
      );
      $("amount").value = d.minimum_valid_bid; // bounce back to the real minimum
      canAnimate(() => {
        animate($("amount"), { x: [0, -6, 6, -3, 0] }, { duration: 0.4, easing: "ease-in-out" });
      });
    } else if (d.reason === "AUCTION_ENDED" || d.reason === "AUCTION_NOT_LIVE") {
      toast("Auction has ended.");
    } else toast("Bid rejected: " + d.reason);
  });

  socket.on("bid_accepted", (d) => {
    const mine = d.request_id === myRequestId;
    if (mine) toast("Bid accepted.");
    if (d.sequence > lastSeq + 1) return reconcile();
    lastSeq = d.sequence;

    $("current-bid").textContent = fmt(d.current_bid);
    if (d.minimum_valid_bid != null) {
      $("min-bid").innerHTML =
        'Minimum valid bid: <span class="tabular-nums">' +
        fmt(d.minimum_valid_bid) + "</span>";
      $("amount").value = d.minimum_valid_bid;
      $("amount").min = d.minimum_valid_bid;
    }
    addHistoryRow(d);

    if (mine) {
      // Successful bid: the headline number springs.
      canAnimate(() => {
        animate($("current-bid"), { scale: [1, 1.12, 1] }, { duration: 0.55, easing: "ease-out" });
        animate($("toast"), { opacity: [0, 1], y: [6, 0] }, { duration: 0.3 });
      });
    } else if (myLastBidAmount && d.bid_amount > myLastBidAmount) {
      // Our bid was countered.
      myLastBidAmount = null;
      toast("Your bid was countered. Current bid: " + fmt(d.current_bid) + ".");
      canAnimate(() => {
        const card = $("current-bid").parentElement;
        animate($("current-bid"), { scale: [1, 0.94, 1] }, { duration: 0.5, easing: "ease-in-out" });
        animate(card, { x: [0, -5, 5, -3, 0] }, { duration: 0.45, easing: "ease-in-out" });
        animate($("min-bid"), { color: ["#9F2F2D", "#111111"] }, { duration: 1.2, easing: "ease-out" });
      });
    }
  });

  function addHistoryRow(d) {
    const li = document.createElement("li");
    li.className = "flex items-center justify-between py-2.5 text-sm";
    const amt = document.createElement("span");
    amt.className = "font-mono tabular-nums";
    amt.textContent = fmt(d.bid_amount);
    const who = document.createElement("span");
    who.className = "text-mute";
    who.textContent = d.bidder || "Bidder";
    const when = document.createElement("span");
    when.className = "text-mute font-mono text-xs";
    when.textContent = new Date().toTimeString().slice(0, 8);
    li.append(amt, who, when);
    $("bid-history").prepend(li);
    return li;
  }

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.dataset.last = msg; // survives the auto-clear so it stays inspectable
    clearTimeout(t._h);
    t._h = setTimeout(() => (t.textContent = ""), 6000);
  }

  $("bid-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const amount = parseInt($("amount").value, 10);
    if (!Number.isFinite(amount)) return;
    myLastBidAmount = amount;
    myRequestId = uuid();
    socket.emit("place_bid", { auction_id: AUCTION_ID, amount, request_id: myRequestId });
  });

  /* ------------------------------------------------------------ end state */

  let endShown = false;
  function showEndState(winner, amount, { celebrate = true } = {}) {
    const overlay = $("end-overlay");
    if (!overlay) return;
    $("end-winner").textContent = winner || "No winner";
    $("end-amount").textContent = winner ? fmt(amount) : "";
    $("end-results").href = "/auction/" + AUCTION_ID + "/results";
    const crown = document.querySelector("[data-crown-lg]");
    if (crown) crown.classList.toggle("hidden", !winner);
    if (endShown) return;
    endShown = true;
    overlay.classList.remove("hidden");
    // force a reflow so the end state (and the confetti canvas) has laid out
    // before the confetti burst sizes its drawing buffer
    void overlay.offsetWidth;
    $("auction-status").textContent = "ENDED";
    $("bid-form").querySelector("button").disabled = true;
    // crown the winner on the leaderboard
    document.querySelectorAll("#leaderboard .leaderboard-row").forEach((row) => {
      const crowned = row.dataset.bidder === winner;
      const badge = row.querySelector("[data-crown]");
      if (badge) badge.classList.toggle("hidden", !crowned);
      if (crowned) row.classList.add("font-medium");
    });
    canAnimate(() => {
      animate($("end-heading"), { opacity: [0, 1], y: [14, 0] }, { duration: 0.5, easing: "ease-out" });
      animate($("end-amount"), { opacity: [0, 1], scale: [0.9, 1] }, { delay: 0.12, duration: 0.5, easing: "ease-out" });
    });
    if (celebrate) burstConfetti();
  }

  function burstConfetti() {
    const canvas = $("confetti-canvas");
    if (!canvas || typeof confetti !== "function" || reduced) return;
    // No worker: a worker-backed instance does not resize a supplied canvas,
    // so nothing would paint. The overlay must be visible before create() so
    // the canvas has real dimensions to size its drawing buffer.
    const fire = confetti.create(canvas, { resize: true, useWorker: false });
    const colors = ["#D4A93F", "#7FBF84", "#6FB1D8", "#D98A8A", "#EDEBE6"];
    fire({ particleCount: 120, spread: 78, origin: { y: 0.62 }, colors });
    setTimeout(() => fire({ particleCount: 90, angle: 60, spread: 60, origin: { x: 0 }, colors }), 180);
    setTimeout(() => fire({ particleCount: 90, angle: 120, spread: 60, origin: { x: 1 }, colors }), 300);
  }

  if ($("end-dismiss"))
    $("end-dismiss").addEventListener("click", () => $("end-overlay").classList.add("hidden"));

  socket.on("auction_ended", (d) => {
    if (d.leaderboard) renderLeaderboard(d.leaderboard, d.winner);
    showEndState(d.winner, d.winning_bid);
  });

  // The countdown is presentation only; the server owns the deadline. At zero
  // we ask for authoritative state and the end state renders from that.
  const endsAt = new Date($("ends-in").dataset.endsAt).getTime();
  const timer = setInterval(() => {
    const s = Math.floor((endsAt - Date.now()) / 1000);
    if (s <= 0) {
      clearInterval(timer);
      $("ends-in").textContent = "ending…";
      // keep asking until the server reports the authoritative end state
      let tries = 0;
      const poll = setInterval(() => {
        socket.emit("request_state", { auction_id: AUCTION_ID });
        if (++tries >= 8 || endShown) clearInterval(poll);
      }, 1500);
      return;
    }
    const m = String(Math.floor(s / 60)).padStart(2, "0");
    $("ends-in").textContent = "ends in " + m + ":" + String(s % 60).padStart(2, "0");
  }, 1000);

  if (boot.dataset.status === "ENDED")
    showEndState(boot.dataset.winner, Number(boot.dataset.winningBid), { celebrate: false });
})();
