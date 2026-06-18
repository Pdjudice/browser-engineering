import tkinter
from lab1 import URL
from lab1 import lex
import unicodedata

WIDTH, HEIGHT = 800, 600

HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100


class Browser:
    def __init__(self):
        self.height = HEIGHT
        self.width = WIDTH
        self.text = ""
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=self.width, height=self.height)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll = 0
        self.window.bind("<Down>", self.scroll_down)
        self.window.bind("<Up>", self.scroll_up)
        self.window.bind("<MouseWheel>", self.scroll_mouse)
        self.window.bind("<Configure>", self.resize)
        self.scrollbar = tkinter.Scrollbar(
            self.window, orient="vertical", command=self.on_scrollbar
        )
        self.scrollbar.pack(side="right", fill="y")

    def resize(self, e):
        self.height = e.height
        self.width = e.width
        self.display_list = self.layout()
        self.draw()

    def on_scrollbar(self, *args):
        fraction = float(args[1])

        max_scroll = max(0, self.end_of_page - self.height)

        self.scroll = int(fraction * max_scroll)
        self.scroll = max(0, min(self.scroll, max_scroll))

        self.draw()

    def scroll_mouse(self, e):
        step = int(-e.delta) * 10

        max_scroll = max(0, self.end_of_page - self.height)

        self.scroll += step
        self.scroll = max(0, min(self.scroll, max_scroll))

        self.draw()

    def scroll_up(self, e):
        self.scroll = max(0, self.scroll - SCROLL_STEP)

        self.draw()

    def scroll_down(self, e):
        max_scroll = max(0, self.end_of_page - self.height)

        self.scroll = min(max_scroll, self.scroll + SCROLL_STEP)
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        self.emoji_cache = {}
        for x, y, c in self.display_list:
            if y > self.scroll + self.height or y + VSTEP < self.scroll:
                continue
            # Exercise 2-5 suggests rendering emojis as images. I kept the reference
            # implementation below, but on my system emojis render more reliably and
            # with better performance when drawn directly using create_text().
            #
            # if self._is_emoji(c):
            #     emoji_path = "emojis/" + self._emoji_to_unicode(c) + ".png"
            #     if emoji_path not in self.emoji_cache:
            #         self.emoji_cache[emoji_path] = tkinter.PhotoImage(file=emoji_path)
            #     self.canvas.create_image(
            #         x, y - self.scroll, image=self.emoji_cache[emoji_path]
            #     )
            # else:
            #     self.canvas.create_text(x, y - self.scroll, text=c)
            self.canvas.create_text(x, y - self.scroll, text=c)
        self.draw_scrollbar()

    def _emoji_to_unicode(self, emoji):
        return "-".join(f"{ord(ch):X}" for ch in emoji)

    def _is_emoji(self, char):
        category = unicodedata.category(char)

        # Emojis primarily belong to the 'So' (Symbol, Other) category
        if category == "So":
            name = unicodedata.name(char, "")
            if "COPYRIGHT" in name or "TRADE MARK" in name:
                return False
            return True

        return False

    def draw_scrollbar(self):
        top = self.scroll / self.end_of_page
        bottom = (self.scroll + self.height) / self.end_of_page
        self.scrollbar.set(top, bottom)
        self.scrollbar.set(top, bottom)

    def load(self, url, rlt_flag=""):
        if rlt_flag == "-rtl":
            self.rlt = True
        else:
            self.rlt = False
        body, content_type = url.request()
        if content_type == "text/html":
            text = lex(body)
        else:
            text = body
        self.text = text

        self.display_list = self.layout()
        self.draw()

    def layout(self):
        if self.rlt:
            return self.rtl_layout()
        else:
            display_list = []
            cursor_x, cursor_y = HSTEP, VSTEP
            for c in self.text:
                if c == "\n":
                    cursor_y += VSTEP
                    display_list.append((cursor_x, cursor_y, c))
                    cursor_x = HSTEP
                    continue
                display_list.append((cursor_x, cursor_y, c))
                cursor_x += HSTEP
                if cursor_x >= self.width - HSTEP:
                    cursor_y += VSTEP
                    cursor_x = HSTEP
            self.end_of_page = cursor_y
            return display_list

    def rtl_layout(self):
        display_list = []
        cursor_x, cursor_y = self.width - HSTEP * 3, VSTEP
        reversedStr = "\n".join(line[::-1] for line in self.text.split("\n"))
        print(reversedStr)
        for c in reversedStr:
            if c == "\n":
                cursor_y += VSTEP
                display_list.append((cursor_x, cursor_y, c))
                cursor_x = self.width - HSTEP * 3
                continue
            display_list.append((cursor_x, cursor_y, c))
            cursor_x -= HSTEP
            if cursor_x <= HSTEP:
                cursor_y += VSTEP
                cursor_x = self.width - HSTEP * 3
        self.end_of_page = cursor_y
        return display_list


if __name__ == "__main__":
    import sys

    rtl = sys.argv[2] if len(sys.argv) > 2 else None

    Browser().load(URL(sys.argv[1]), rtl)
    tkinter.mainloop()
