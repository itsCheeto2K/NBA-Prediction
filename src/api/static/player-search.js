(() => {
  document.addEventListener("DOMContentLoaded", () => {
    const trigger = document.getElementById("btn-player-search");
    if (!trigger) return;
    const dialog = document.createElement("dialog");
    dialog.id = "player-search-dialog";
    dialog.className = "player-search-dialog";
    dialog.setAttribute("aria-label", "Tìm cầu thủ");
    dialog.innerHTML = `
      <div class="player-search-input-row">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>
        <input id="player-search" type="search" placeholder="Tìm tên cầu thủ…" aria-label="Tên cầu thủ" autocomplete="off" autofocus>
        <button type="button" class="player-search-close" aria-label="Đóng tìm kiếm">✕</button>
      </div>
      <p class="player-search-status" role="status" aria-live="polite">Gợi ý</p>
      <div class="player-search-results" aria-label="Kết quả tìm kiếm"></div>`;
    document.body.appendChild(dialog);
    const input = dialog.querySelector("input");
    const results = dialog.querySelector(".player-search-results");
    const status = dialog.querySelector(".player-search-status");
    let version = 0, controller = null, timer = null;

    function cancelSearch() {
      version++;
      clearTimeout(timer);
      if (controller) controller.abort();
    }
    function choose(player) {
      dialog.close();
      if (typeof window.selectPlayer === "function") window.selectPlayer(player.player_id, player.full_name);
      else window.location.assign(`/?player_id=${player.player_id}&player_name=${encodeURIComponent(player.full_name)}`);
    }
    function render(players) {
      results.replaceChildren();
      players.forEach(player => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "player-search-result";
        button.textContent = player.full_name;
        button.addEventListener("click", () => choose(player));
        results.appendChild(button);
      });
    }
    function search() {
      cancelSearch();
      const requestVersion = version;
      const query = input.value.trim();
      render([]);
      if (query && query.length < 2) {
        status.textContent = "Nhập ít nhất 2 ký tự để tìm kiếm.";
        return;
      }
      status.textContent = query ? "Đang tìm kiếm…" : "Đang tải gợi ý…";
      timer = setTimeout(async () => {
        controller = new AbortController();
        try {
          const response = await fetch(`/api/players?query=${encodeURIComponent(query)}&active_only=true`, {signal:controller.signal});
          const players = (await readApiResponse(response)).filter(player => player.membership_verified === true);
          if (requestVersion !== version || !dialog.open) return;
          render(players);
          status.textContent = players.length ? (query ? `${players.length} cầu thủ` : "Gợi ý") : "Không tìm thấy cầu thủ trong roster hiện tại.";
        } catch (error) {
          if (error.name === "AbortError" || requestVersion !== version || !dialog.open) return;
          status.textContent = error.message || "Không tải được kết quả. Vui lòng thử lại.";
        }
      }, 200);
    }
    trigger.addEventListener("click", () => {
      input.value = "";
      dialog.showModal();
      trigger.setAttribute("aria-expanded", "true");
      search();
      input.focus();
    });
    input.addEventListener("input", search);
    input.addEventListener("keydown", event => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        results.querySelector("button")?.focus();
      } else if (event.key === "Enter") {
        event.preventDefault();
        results.querySelector("button")?.click();
      }
    });
    dialog.querySelector(".player-search-close").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", event => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    });
    dialog.addEventListener("close", () => {
      cancelSearch();
      trigger.setAttribute("aria-expanded", "false");
      trigger.focus();
    });
  });
})();
