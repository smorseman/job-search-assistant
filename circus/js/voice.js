// Web Speech API wrapper — German recognition, Bavarian synthesis.

const VOICE = (() => {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canListen = !!SpeechRecognition;
  const canSpeak  = !!window.speechSynthesis;

  let recognition = null;
  let listening = false;

  // Prefers de-AT (Austrian German, closest Bavarian-adjacent voice available)
  // Falls back to de-DE
  let selectedVoice = null;

  function loadVoices() {
    if (!canSpeak) return;
    const load = () => {
      const voices = speechSynthesis.getVoices();
      selectedVoice =
        voices.find(v => v.lang === "de-AT") ||
        voices.find(v => v.lang === "de-DE") ||
        voices.find(v => v.lang.startsWith("de")) ||
        null;
    };
    // getVoices() is async on first call in some browsers
    if (speechSynthesis.getVoices().length) {
      load();
    } else {
      speechSynthesis.onvoiceschanged = load;
    }
  }

  function speak(text) {
    if (!canSpeak) return;
    speechSynthesis.cancel(); // stop any in-progress utterance
    const utt = new SpeechSynthesisUtterance(text);
    utt.lang  = "de-AT";
    utt.rate  = 0.92;
    utt.pitch = 1.05;
    if (selectedVoice) utt.voice = selectedVoice;
    speechSynthesis.speak(utt);
  }

  function startListening(onResult, onError) {
    if (!canListen) {
      onError && onError("SpeechRecognition not supported in this browser.");
      return;
    }
    if (listening) return;

    recognition = new SpeechRecognition();
    recognition.lang = "de-DE";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = e => {
      const transcript = e.results[0][0].transcript;
      onResult && onResult(transcript);
    };
    recognition.onerror = e => {
      listening = false;
      onError && onError(e.error);
    };
    recognition.onend = () => { listening = false; };

    recognition.start();
    listening = true;
  }

  function stopListening() {
    if (recognition && listening) {
      recognition.stop();
      listening = false;
    }
  }

  loadVoices();

  return { canListen, canSpeak, speak, startListening, stopListening,
           get listening() { return listening; } };
})();
