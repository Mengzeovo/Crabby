import type { ConversationSnapshot } from "../shared/types";

const bubbleCard = document.getElementById("bubbleCard") as HTMLElement;
const bubbleMessage = document.getElementById("bubbleMessage") as HTMLParagraphElement;
const bubbleAction = document.getElementById("bubbleAction") as HTMLButtonElement;

function renderSnapshot(snapshot: ConversationSnapshot): void {
  bubbleMessage.textContent = snapshot.bubble.message || "Background task finished.";
}

async function openChatFromBubble(): Promise<void> {
  await window.desktopPet.openChatWindow();
  await window.desktopPet.dismissBubble();
}

bubbleAction.addEventListener("click", (event) => {
  event.stopPropagation();
  void openChatFromBubble();
});

bubbleCard.addEventListener("click", () => {
  void openChatFromBubble();
});

window.desktopPet.subscribeConversationSnapshot(renderSnapshot);

void (async () => {
  renderSnapshot(await window.desktopPet.getConversationSnapshot());
})();
