"""UTF-8 radio formatting and concise, bounded lookup summaries."""

import os

MESSAGE_BYTES = 150


def counted(count, singular, plural=None):
    """Format a count and noun; zero and values other than one use the plural."""
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def clean_text(text):
    """Normalize horizontal whitespace while retaining meaningful line boundaries."""
    text = "".join(c for c in str(text) if c.isprintable() or c.isspace())
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def take_text(text, budget):
    """Take a byte-bounded prefix, preferring lines and then whole words.

    A token larger than a complete message must be split, but UTF-8 characters
    remain intact. Ordinary URLs move intact to the next message.
    """
    if len(text.encode("utf-8")) <= budget:
        return text, ""
    piece = text.encode("utf-8")[:budget].decode("utf-8", "ignore")
    if not piece:
        raise ValueError("Reply budget cannot hold one UTF-8 character")
    boundary = piece.rfind("\n")
    if boundary < len(piece) // 3:
        boundary = max(piece.rfind(" "), piece.rfind("\n"))
    # A boundary immediately after the prefix also preserves a complete token.
    if len(piece) < len(text) and text[len(piece)].isspace():
        boundary = len(piece)
    if boundary > 0:
        piece = piece[:boundary]
    return piece.rstrip(), text[len(piece):].lstrip()


def split_text(text, budget):
    """Return all chunks without dropping content or imposing a part count."""
    result = []
    while text:
        piece, text = take_text(text, budget)
        result.append(piece)
    return result


def tagged_parts(sender, output, limit=MESSAGE_BYTES, max_parts=4):
    """Tag and number byte-bounded chunks without radio omission notices."""
    if max_parts < 1:
        raise ValueError("Reply part limit must be positive")
    prefix = f"@{sender} "
    budget = limit - len(prefix.encode("utf-8"))
    text = clean_text(output) or "The script returned no text."
    if budget < 4:
        raise ValueError("Sender name leaves insufficient room for a reply")
    if len(text.encode("utf-8")) <= budget:
        return [prefix + text]
    # Reserve the widest permitted counter before deciding chunk boundaries.
    counter_bytes = len(f"[{max_parts}/{max_parts}] ") if max_parts > 1 else 0
    body_budget = budget - counter_bytes
    if body_budget < 4:
        raise ValueError("Reply limit leaves insufficient room for numbering")
    chunks = split_text(text, body_budget)
    if len(chunks) > max_parts:
        chunks = chunks[:max_parts]
    total = len(chunks)
    return [prefix + (f"[{i}/{total}] " if total > 1 else "") + body
            for i, body in enumerate(chunks, 1)]


def short_label(value, budget=60):
    """Bound variable names and identifiers, never hazard instructions or measurements."""
    value = " ".join(str(value).split())
    if len(value.encode()) <= budget:
        return value
    prefix, _ = take_text(value, budget - 3)
    return prefix + "..."


def split_fields(text, separator="; "):
    """Split top-level fields, retaining parenthetical and bracketed qualifiers whole.

    An unmatched opening delimiter keeps the remaining text together rather than
    allowing a partial qualification to become an independent radio field.
    """
    fields, stack, start, index = [], [], 0, 0
    closing = {"(": ")", "[": "]", "{": "}"}
    while index < len(text):
        character = text[index]
        if character in closing:
            stack.append(closing[character])
        elif stack and character == stack[-1]:
            stack.pop()
        elif not stack and text.startswith(separator, index):
            fields.append(text[start:index])
            index += len(separator)
            start = index
            continue
        index += 1
    return fields + [text[start:]]


def compact_fields(essential, fields=(), sender=None):
    """Fit complete optional fields after essential safety/status text in one message.

    Optional names, times and secondary measurements are admitted only as whole
    fields. No omission notices or continuation prompts are transmitted. Essential
    text is never cut mid-sentence; owning formatters must keep it short enough
    for the longest supported sender tag.
    """
    sender = os.environ.get("MESHCORE_SENDER", "Reader") if sender is None else sender
    budget = MESSAGE_BYTES - len(f"@{sender} ".encode())
    pieces = split_fields(clean_text(essential), " | ")
    essential = pieces[0]
    fields = pieces[1:] + [clean_text(value) for value in fields if value]
    if len(essential.encode()) > budget:
        return "Unable to return this result."
    selected = essential
    seen = {essential}
    for field in fields:
        if field in seen:
            continue
        candidate = selected + " | " + field
        if len(candidate.encode()) <= budget:
            selected = candidate
            seen.add(field)
    return selected
