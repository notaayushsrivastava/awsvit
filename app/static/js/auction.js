(() => {
  const boot = document.getElementById("bootstrap");
  const AUCTION_ID = boot.dataset.auctionId;
  const fmt = (n) => n.toLocaleString("en-IN");
  const $ = (id) => document.getElementById(id);

  const socket = io();
  let myLastBidAmount = null;
  let myRequestId = null;

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
  socket.on("server_error", (d) => toast(d.error));

  // gap detection: an event whose sequence is more than +1 past what we saw
  // means we missed something — reconcile from the server snapshot.
  let lastSeq = Number(boot.dataset.seq);
  function reconcile() {
    socket.emit("request_state", { auction_id: AUCTION_ID });
  }

  socket.on("auction_state", (state) => {
    lastSeq = state.sequence;
    $("current-bid").textContent = fmt(state.current_bid);
    $("min-bid").innerHTML =
      'Minimum valid bid: <span class="tabular-nums">' +
      fmt(state.minimum_valid_bid) + "</span>";
    $("amount").value = state.minimum_valid_bid;
    $("amount").min = state.minimum_valid_bid;
    $("auction-status").textContent = state.status;
    if (state.status !== "LIVE") $("bid-form").querySelector("button").disabled = true;
  });

  socket.on("bid_rejected", (d) => {
    myLastBidAmount = null;
    if (d.reason === "BID_TOO_LOW")
      toast(
        "Bid rejected. Current bid: " + fmt(d.current_bid) +
        ". Minimum valid bid: " + fmt(d.minimum_valid_bid) + "."
      );
    else if (d.reason === "AUCTION_ENDED" || d.reason === "AUCTION_NOT_LIVE")
      toast("Auction has ended.");
    else toast("Bid rejected: " + d.reason);
  });

  socket.on("bid_accepted", (d) => {
    if (d.request_id === myRequestId) toast("Bid accepted.");
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
    if (myLastBidAmount && d.bid_amount > myLastBidAmount) {
      toast("You were outbid. Current bid: " + fmt(d.current_bid) + ".");
    }
  });

  socket.on("auction_ended", (d) => {
    $("auction-status").textContent = "ENDED";
    $("bid-form").querySelector("button").disabled = true;
    const w = $("winner-box");
    w.classList.remove("hidden");
    w.textContent = d.winner
      ? "Winner: " + d.winner + " at " + fmt(d.winning_bid)
      : "No bids received.";
    const link = document.createElement("a");
    link.href = "/auction/" + AUCTION_ID + "/results";
    link.textContent = "View results";
    link.className =
      "mt-2 inline-block text-sm text-mute underline underline-offset-4 hover:text-ink transition";
    w.appendChild(document.createElement("br"));
    w.appendChild(link);
  });

  function addHistoryRow(d) {
    const li = document.createElement("li");
    li.className = "flex items-center justify-between py-2.5 text-sm";
    li.innerHTML =
      '<span class="font-mono tabular-nums">' + fmt(d.bid_amount) + "</span>" +
      '<span class="text-mute">' + (d.bidder || "Bidder") + "</span>" +
      '<span class="text-mute font-mono text-xs">' +
      new Date().toTimeString().slice(0, 8) + "</span>";
    $("bid-history").prepend(li);
  }

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    clearTimeout(t._h);
    t._h = setTimeout(() => (t.textContent = ""), 6000);
  }

  $("bid-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const amount = parseInt($("amount").value, 10);
    if (!Number.isFinite(amount)) return;
    myLastBidAmount = amount;
    myRequestId = crypto.randomUUID();
    socket.emit("place_bid", { auction_id: AUCTION_ID, amount, request_id: myRequestId });
  });

  // countdown from the authoritative server timestamp
  const endsAt = new Date($("ends-in").dataset.endsAt).getTime();
  setInterval(() => {
    const s = Math.floor((endsAt - Date.now()) / 1000);
    if (s <= 0) return;
    const m = String(Math.floor(s / 60)).padStart(2, "0");
    $("ends-in").textContent = "ends in " + m + ":" + String(s % 60).padStart(2, "0");
  }, 1000);
})();
