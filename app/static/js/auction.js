(() => {
  const boot = document.getElementById("bootstrap");
  const AUCTION_ID = boot.dataset.auctionId;
  const fmt = (n) => n.toLocaleString("en-IN");
  const $ = (id) => document.getElementById(id);

  const socket = io();
  let myLastBidAmount = null;

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
    socket.emit("request_state", { auction_id: AUCTION_ID }, (res) => {
      if (res.ok) {
        lastSeq = res.state.sequence;
        $("current-bid").textContent = fmt(res.state.current_bid);
        if (res.state.status !== "LIVE") {
          $("auction-status").textContent = res.state.status;
          $("bid-form").querySelector("button").disabled = true;
        }
      }
    });
  }

  socket.on("bid_accepted", (d) => {
    if (d.sequence > lastSeq + 1) return reconcile();
    lastSeq = d.sequence;
    $("current-bid").textContent = fmt(d.current_bid);
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
    socket.emit(
      "place_bid",
      { auction_id: AUCTION_ID, amount, request_id: crypto.randomUUID() },
      (res) => {
        if (res.ok) toast("Bid accepted.");
        else if (res.reason === "BID_TOO_LOW")
          toast(
            "Bid rejected. Current bid: " + fmt(res.current_bid) +
            ". Minimum valid bid: " + fmt(res.minimum_valid_bid) + "."
          );
        else if (res.reason === "AUCTION_ENDED" || res.reason === "AUCTION_NOT_LIVE")
          toast("Auction has ended.");
        else toast("Bid rejected: " + res.reason);
      }
    );
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
