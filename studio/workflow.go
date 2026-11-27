package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type option struct{ Value, Label string }
type workflowEvent struct {
	Kind, Mode, Text string
	ID, Default      int
	Options          []option
}
type workflowProcess struct {
	cmd    *exec.Cmd
	input  io.WriteCloser
	reader *bufio.Scanner
}
type workflowStarted struct {
	p   *workflowProcess
	err error
}
type workflowMessage struct {
	event workflowEvent
	eof   bool
	err   error
}
type workflowTick struct{}
type workflow struct {
	label                 string
	process               *workflowProcess
	prompt                *workflowEvent
	input                 textinput.Model
	cursor, scroll, width int
	raw                   string
	lines                 []string
	finished, cancelling  bool
	note                  string
	started               time.Time
}

func startWorkflow(m model, a action) tea.Cmd {
	return func() tea.Msg {
		c := exec.Command(m.python, "-u", m.bridge, "workflow", m.core, a.Key)
		in, e := c.StdinPipe()
		if e != nil {
			return workflowStarted{err: e}
		}
		out, e := c.StdoutPipe()
		if e != nil {
			in.Close()
			return workflowStarted{err: e}
		}
		// Startup failures must not overwrite the alternate screen.
		c.Stderr = io.Discard
		if e = c.Start(); e != nil {
			in.Close()
			return workflowStarted{err: e}
		}
		scan := bufio.NewScanner(out)
		scan.Buffer(make([]byte, 8192), 256*1024)
		return workflowStarted{p: &workflowProcess{c, in, scan}}
	}
}
func nextWorkflow(p *workflowProcess) tea.Cmd {
	return func() tea.Msg {
		if p.reader.Scan() {
			var e workflowEvent
			if err := json.Unmarshal(p.reader.Bytes(), &e); err != nil {
				_ = p.input.Close()
				_ = p.cmd.Process.Signal(os.Interrupt)
				for p.reader.Scan() {
				}
				_ = p.cmd.Wait()
				return workflowMessage{eof: true, err: err}
			}
			return workflowMessage{event: e}
		}
		_ = p.input.Close()
		err := p.reader.Err()
		wait := p.cmd.Wait()
		if err == nil {
			err = wait
		}
		return workflowMessage{eof: true, err: err}
	}
}
func tickWorkflow() tea.Cmd {
	return tea.Tick(time.Second, func(time.Time) tea.Msg { return workflowTick{} })
}
func newWorkflow(a action) *workflow {
	ti := textinput.New()
	ti.CharLimit = 8192
	return &workflow{label: a.Label, input: ti, started: time.Now()}
}
func wrapPlain(s string, width int) []string {
	width = max(1, width)
	result := []string{}
	var b strings.Builder
	n := 0
	for _, r := range s {
		if r == '\n' {
			result = append(result, b.String())
			b.Reset()
			n = 0
			continue
		}
		rw := lipgloss.Width(string(r))
		if n+rw > width && n > 0 {
			result = append(result, b.String())
			b.Reset()
			n = 0
		}
		if rw <= width {
			b.WriteRune(r)
			n += rw
		}
	}
	return append(result, b.String())
}
func (f *workflow) append(s string) { f.raw += s; f.width = 0 }
func (f *workflow) reflow(w int) {
	if w != f.width {
		f.lines = wrapPlain(f.raw, w)
		f.width = w
	}
}
func (f *workflow) reply(value string, cancel bool) error {
	if f.process == nil || f.prompt == nil {
		return fmt.Errorf("No pending input")
	}
	b, e := json.Marshal(map[string]any{"id": f.prompt.ID, "value": value, "cancel": cancel})
	if e != nil {
		return e
	}
	_, e = f.process.input.Write(append(b, '\n'))
	if e == nil {
		f.prompt = nil
		f.input.Blur()
		f.scroll = 0
	}
	return e
}
func (m model) updateWorkflow(msg tea.Msg) (tea.Model, tea.Cmd) {
	f := m.flow
	switch v := msg.(type) {
	case workflowStarted:
		if v.err != nil {
			f.finished = true
			f.note = "Could not start workflow: " + v.err.Error()
			return m, nil
		}
		f.process = v.p
		return m, tea.Batch(nextWorkflow(v.p), tickWorkflow())
	case workflowMessage:
		if v.eof {
			f.finished = true
			f.prompt = nil
			f.note = "Workflow closed. Review output; no automatic retry."
			if v.err != nil {
				f.note = "Workflow interrupted or failed. Inspect state before retrying."
			}
			return m, nil
		}
		e := v.event
		switch e.Kind {
		case "output":
			f.append(e.Text)
		case "prompt":
			f.append("\n" + e.Text + "\n")
			f.prompt = &e
			f.cursor = max(0, min(e.Default, len(e.Options)-1))
			f.input.SetValue("")
			f.scroll = 0
			if e.Mode == "text" {
				f.input.Focus()
			}
		case "done":
			f.note = e.Text
		}
		return m, nextWorkflow(f.process)
	case workflowTick:
		if !f.finished {
			return m, tickWorkflow()
		}
		return m, nil
	case tea.WindowSizeMsg:
		m.width = v.Width
		m.height = v.Height
		return m, nil
	case tea.KeyMsg:
		k := v.String()
		if k == "pgup" || k == "ctrl+u" {
			f.scroll = min(max(0, len(f.lines)-1), f.scroll+max(1, m.height/3))
			return m, nil
		}
		if k == "pgdown" || k == "ctrl+d" {
			f.scroll = max(0, f.scroll-max(1, m.height/3))
			return m, nil
		}
		if f.finished {
			if k == "enter" || k == "esc" || k == "ctrl+c" {
				m.flow = nil
				m.page = "home"
				m.cursor = 0
				m.input.SetValue("")
				m.input.Blur()
				m.loading = true
				m.note = "Repository refreshed after workflow."
				return m, m.refresh()
			}
			return m, nil
		}
		if k == "esc" || k == "ctrl+c" || k == "ctrl+q" {
			if f.cancelling {
				return m, nil
			}
			if f.prompt != nil {
				if e := f.reply("", true); e != nil {
					f.note = e.Error()
				}
			} else if f.process != nil {
				_ = f.process.cmd.Process.Signal(os.Interrupt)
			} else {
				return m, nil
			}
			f.cancelling = true
			f.note = "Cancellation requested. Inspect state after action returns."
			return m, nil
		}
		if f.prompt == nil {
			return m, nil
		}
		if m.height < 16 || m.width < 38 {
			f.note = "Enlarge terminal to review and submit safely."
			return m, nil
		}
		if f.prompt.Mode == "text" {
			if k == "enter" {
				if e := f.reply(f.input.Value(), false); e != nil {
					f.note = e.Error()
				}
				return m, nil
			}
			var c tea.Cmd
			f.input, c = f.input.Update(msg)
			return m, c
		}
		switch k {
		case "up":
			f.cursor = max(0, f.cursor-1)
		case "down":
			f.cursor = min(len(f.prompt.Options)-1, f.cursor+1)
		case "enter":
			if f.cursor >= 0 && f.cursor < len(f.prompt.Options) {
				if e := f.reply(f.prompt.Options[f.cursor].Value, false); e != nil {
					f.note = e.Error()
				}
			}
		}
		return m, nil
	}
	if f.prompt != nil && f.prompt.Mode == "text" {
		var c tea.Cmd
		f.input, c = f.input.Update(msg)
		return m, c
	}
	return m, nil
}
func (m model) workflowView(w, h int) string {
	f := m.flow
	rows := []string{}
	if h >= 18 {
		rows = append(rows, logo(w)...)
	} else {
		rows = append(rows, brand.Render(fit("gitappho. / STUDIO", w)))
	}
	rows = append(rows, violet.Render(fit("WORKFLOW / "+f.label, w)))
	if h < 15 || w < 36 {
		rows = append(rows, warn.Render(fit("Enlarge terminal to review / submit. Esc cancels.", w)))
		return strings.Join(rows[:min(h, len(rows))], "\n")
	}
	inner := max(1, w-4)
	room := max(1, h-len(rows)-1)
	controls := []string{}
	title := "EXECUTION"
	if f.prompt != nil {
		title = "REVIEW / INPUT"
		p := f.prompt
		prompt := wrapPlain(p.Text, inner)
		maxTitle := max(1, min(4, room/4))
		if len(prompt) > maxTitle {
			prompt = append(prompt[:maxTitle-1], fit("Full prompt in activity log", inner))
		}
		for _, s := range prompt {
			controls = append(controls, brand.Render(s))
		}
		if p.Mode == "text" {
			ti := f.input
			ti.Width = max(1, inner-3)
			controls = append(controls, ti.View())
		} else {
			n := max(1, min(len(p.Options), room/2-len(controls)))
			start := max(0, min(f.cursor-n+1, len(p.Options)-n))
			for i := start; i < min(len(p.Options), start+n); i++ {
				s := fit("  "+p.Options[i].Label, inner)
				if i == f.cursor {
					s = selected.Render(pad(fit("❯ "+p.Options[i].Label, inner), inner))
				} else {
					s = muted.Render(s)
				}
				controls = append(controls, s)
			}
		}
	} else if f.finished {
		controls = append(controls, brand.Render(fit("Review results · Enter returns to dashboard", inner)))
	} else {
		controls = append(controls, brand.Render(fit(fmt.Sprintf("◌ Working… %ds", int(time.Since(f.started).Seconds())), inner)))
	}
	if f.note != "" && len(controls) < max(1, room/2) {
		controls = append(controls, warn.Render(fit(f.note, inner)))
	}
	// Always reserve the prompt controls, even in a short terminal.
	controlBudget := max(1, room-3)
	if len(controls) > controlBudget {
		controls = controls[len(controls)-controlBudget:]
	}
	logBudget := max(0, room-len(controls)-4)
	f.reflow(inner)
	if logBudget > 0 {
		end := max(0, len(f.lines)-min(f.scroll, max(0, len(f.lines)-1)))
		start := max(0, end-logBudget)
		log := []string{}
		for _, s := range f.lines[start:end] {
			log = append(log, muted.Render(s))
		}
		for len(log) < logBudget {
			log = append(log, "")
		}
		rows = append(rows, strings.Split(panel("ACTIVITY / PgUp PgDn", log, w), "\n")...)
	}
	if len(rows)+len(controls)+2 < h {
		rows = append(rows, strings.Split(panel(title, controls, w), "\n")...)
	} else {
		rows = append(rows, controls...)
	}
	footer := "↑↓ Select · Enter Submit · PgUp/PgDn Activity · Esc Cancel action"
	if f.finished {
		footer = "Enter / Esc Home · PgUp/PgDn Review output"
	}
	if f.prompt == nil && !f.finished {
		footer = "PgUp/PgDn Activity · Ctrl+C Interrupt"
	}
	if len(rows) < h {
		rows = append(rows, muted.Render(fit(footer, w)))
	}
	return strings.Join(rows[:min(h, len(rows))], "\n")
}
