document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("user-input");
    const chatBox = document.getElementById("chat-box");
    const sendBtn = document.getElementById("send-btn");

    function appendMessage(sender, message) {
        const msgDiv = document.createElement("div");
        msgDiv.classList.add("chat-message");
        msgDiv.classList.add(sender === "You" ? "user-message" : "bot-message");
        msgDiv.textContent = message;
        chatBox.appendChild(msgDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    function sendMessage() {
        const message = input.value.trim();
        if (!message) return;

        appendMessage("You", message);
        input.value = "";

        fetch("/api/chatbot", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message })
        })
        .then(res => res.json())
        .then(data => appendMessage("Bot", data.message))
        .catch(() => appendMessage("Bot", "Error connecting to chatbot."));
    }

    sendBtn.addEventListener("click", sendMessage);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });
});
