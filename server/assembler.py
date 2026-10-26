"""
Transcript Assembler for PhoneMic LAN.
Handles streaming hypothesis consolidation, boundary deduplication,
and conservative text formatting (capitalization & sentence bounds).
"""

from typing import Tuple, List

class TranscriptAssembler:
    """
    Maintains streaming transcription state.
    Separates committed tokens from active provisional hypotheses.
    """
    def __init__(self):
        self.committed_words: List[str] = []
        self.provisional_text: str = ""

    def update_hypothesis(self, raw_chunk_hypothesis: str) -> Tuple[str, str]:
        """
        Processes new partial output from streaming ASR.
        Returns: (committed_text, full_display_text)
        """
        cleaned = raw_chunk_hypothesis.strip()
        if not cleaned:
            return self.get_committed_text(), self.get_full_text()
        
        words = cleaned.split()
        
        # Deduplication against recently committed words
        if self.committed_words and words:
            # Check overlap between tail of committed and head of new words
            overlap_len = 0
            max_check = min(len(self.committed_words), len(words), 4)
            for k in range(max_check, 0, -1):
                tail = [w.lower() for w in self.committed_words[-k:]]
                head = [w.lower() for w in words[:k]]
                if tail == head:
                    overlap_len = k
                    break
            if overlap_len > 0:
                words = words[overlap_len:]
        
        self.provisional_text = " ".join(words)
        return self.get_committed_text(), self.get_full_text()

    def commit_provisional(self) -> str:
        """Commits current provisional words to the permanent stream history."""
        if self.provisional_text:
            for w in self.provisional_text.split():
                self.committed_words.append(w)
            self.provisional_text = ""
        return self.get_committed_text()

    def finalize(self) -> str:
        """Flushes remaining provisional text and returns formatted final transcript."""
        self.commit_provisional()
        raw = self.get_committed_text()
        return self.format_transcript(raw)

    def get_committed_text(self) -> str:
        return " ".join(self.committed_words)

    def get_full_text(self) -> str:
        committed = self.get_committed_text()
        if committed and self.provisional_text:
            return f"{committed} {self.provisional_text}"
        return committed or self.provisional_text

    @staticmethod
    def format_transcript(text: str) -> str:
        """Conservative punctuation and capitalization formatting."""
        s = text.strip()
        if not s:
            return ""
        # Capitalize first character
        s = s[0].upper() + s[1:]
        # Add period if not ending with standard punctuation
        if s[-1] not in (".", "!", "?", ",", ":", ";"):
            s += "."
        return s
