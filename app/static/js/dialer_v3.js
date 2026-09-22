
document.addEventListener("DOMContentLoaded", () => {
  const callButton = document.querySelector(".call-next-button");

  if (!callButton) return;

  const form = callButton.closest("form");

  if (!form) return;

  form.addEventListener("submit", () => {
    if (callButton.disabled) return;

    callButton.disabled = true;

    const mainText = callButton.querySelector(".call-button-copy strong");
    const subText = callButton.querySelector(".call-button-copy small");

    if (mainText) mainText.textContent = "Starting Call…";
    if (subText) subText.textContent = "Twilio is connecting your agent phone.";
  });
});
