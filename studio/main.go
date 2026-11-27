package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type action struct{ Key, Label, Group, Words, Blocked string }
type snapshot struct {
	Project, Branch, Connection, Working, Blocked string
	Operation, History                            []string
	Actions                                       []action
	Stash                                         int
}
type snapshotMsg struct {
	data snapshot
	err  error
}

type model struct {
	core, bridge, python  string
	data                  snapshot
	input                 textinput.Model
	width, height, cursor int
	page                  string
	loading               bool
	note                  string
	pending               *action
	flow                  *workflow
}

var accent = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#6539A5", Dark: "#D0A7FF"}).Bold(true)
var pink = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#A62A75", Dark: "#FA8AD8"}).Bold(true)
var muted = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#60606B", Dark: "#A49AB1"})
var warn = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#895400", Dark: "#F5C77D"})
var chosen = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#6539A5", Dark: "#E9D4FF"}).Bold(true)

func (m model) refresh() tea.Cmd {
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		b, e := exec.CommandContext(ctx, m.python, m.bridge, "snapshot", m.core).Output()
		if e != nil {
			return snapshotMsg{err: e}
		}
		var d snapshot
		e = json.Unmarshal(b, &d)
		return snapshotMsg{d, e}
	}
}
func (m model) Init() tea.Cmd { return m.refresh() }
func (m model) list() []action {
	out := []action{}
	q := strings.Fields(strings.ToLower(m.input.Value()))
	for _, a := range m.data.Actions {
		if m.page == "home" && a.Key != "save" && a.Key != "update" && a.Key != "new" && a.Key != "combine" && a.Key != "fix" {
			continue
		}
		hay := strings.ToLower(a.Key + " " + a.Label + " " + a.Group + " " + a.Words)
		ok := true
		for _, t := range q {
			if !strings.Contains(hay, t) {
				ok = false
				break
			}
		}
		if ok {
			out = append(out, a)
		}
	}
	return out
}
func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if m.flow != nil {
		return m.updateWorkflow(msg)
	}
	switch v := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = v.Width
		m.height = v.Height
		m.input.Width = max(10, min(60, m.width-12))
		return m, nil
	case snapshotMsg:
		m.loading = false
		m.cursor = 0
		if v.err != nil {
			m.data = snapshot{Blocked: "Could not inspect project. Press F5 to retry."}
			m.note = "No action was executed."
		} else {
			m.data = v.data
		}
		return m, nil
	case tea.KeyMsg:
		k := v.String()
		if k == "ctrl+c" || k == "ctrl+q" {
			return m, tea.Quit
		}
		if m.pending != nil {
			switch k {
			case "esc", "n":
				m.pending = nil
				return m, nil
			case "enter", "y":
				a := *m.pending
				m.pending = nil
				m.flow = newWorkflow(a)
				return m, startWorkflow(m, a)
			}
			return m, nil
		}
		switch k {
		case "f5":
			if !m.loading {
				m.loading = true
				return m, m.refresh()
			}
			return m, nil
		case "ctrl+p":
			m.page = "search"
			m.cursor = 0
			m.input.SetValue("")
			return m, m.input.Focus()
		case "esc":
			if m.page != "home" {
				m.page = "home"
				m.input.SetValue("")
				m.input.Blur()
				m.cursor = 0
				return m, nil
			}
			return m, tea.Quit
		case "tab":
			m.cursor = 0
			m.input.SetValue("")
			m.input.Blur()
			if m.page == "home" {
				m.page = "history"
			} else if m.page == "history" {
				m.page = "search"
				return m, m.input.Focus()
			} else {
				m.page = "home"
			}
			return m, nil
		case "up":
			if m.cursor > 0 {
				m.cursor--
			}
			return m, nil
		case "down":
			if m.cursor+1 < len(m.list()) {
				m.cursor++
			}
			return m, nil
		case "enter":
			if m.loading || m.data.Blocked != "" || m.page == "history" {
				return m, nil
			}
			a := m.list()
			if m.cursor >= len(a) {
				return m, nil
			}
			if a[m.cursor].Blocked != "" {
				m.note = a[m.cursor].Blocked
				return m, nil
			}
			m.flow = newWorkflow(a[m.cursor])
			return m, startWorkflow(m, a[m.cursor])
		}
	}
	if m.page == "search" && m.pending == nil {
		var c tea.Cmd
		old := m.input.Value()
		m.input, c = m.input.Update(msg)
		if old != m.input.Value() {
			m.cursor = 0
		}
		return m, c
	}
	return m, nil
}

// Studio Identity: a responsive, pixel-built wordmark and a compact workspace.
var brand = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#176C61", Dark: "#A1F4D0"}).Bold(true)
var violet = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#6242A0", Dark: "#B6A1FF"}).Bold(true)
var frame = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#6957A0", Dark: "#6A5A96"})
var selected = lipgloss.NewStyle().Foreground(lipgloss.Color("#131420")).Background(lipgloss.Color("#B6A1FF")).Bold(true)

// All inputs here are plain text, never pre-styled terminal strings.
func fit(s string, n int) string {
	if n <= 0 {
		return ""
	}
	if lipgloss.Width(s) <= n {
		return s
	}
	if n == 1 {
		return "…"
	}
	var b strings.Builder
	for _, r := range s {
		if lipgloss.Width(b.String()+string(r)) > n-1 {
			break
		}
		b.WriteRune(r)
	}
	return b.String() + "…"
}
func pad(s string, n int) string { return s + strings.Repeat(" ", max(0, n-lipgloss.Width(s))) }
func panel(label string, lines []string, width int) string {
	if width < 6 {
		return strings.Join(lines, "\n")
	}
	title := fit(" "+label+" ", width-2)
	top := frame.Render("╭") + violet.Render(title) + frame.Render(strings.Repeat("─", max(0, width-2-lipgloss.Width(title)))+"╮")
	rows := []string{top}
	for _, line := range lines {
		rows = append(rows, frame.Render("│")+pad(line, width-2)+frame.Render("│"))
	}
	rows = append(rows, frame.Render("╰"+strings.Repeat("─", width-2)+"╯"))
	return strings.Join(rows, "\n")
}
func logo(width int) []string {
	// Original compact 3x6 bitmap glyphs; each terminal cell packs two pixels.
	glyphs := map[rune][]string{
		'G': {"111", "100", "101", "101", "111", "000"},
		'I': {"111", "010", "010", "010", "111", "000"},
		'T': {"111", "010", "010", "010", "010", "000"},
		'A': {"010", "101", "111", "101", "101", "000"},
		'P': {"110", "101", "110", "100", "100", "000"},
		'H': {"101", "101", "111", "101", "101", "000"},
		'O': {"111", "101", "101", "101", "111", "000"},
	}
	if width < 38 {
		return []string{brand.Render(fit("gitappho.", width))}
	}
	colors := []string{"#9AF5CF", "#91E8D4", "#8BDDDC", "#92CFE9", "#A0BDF4", "#ACAFFF", "#B7A1FF", "#C397FF"}
	rows := []string{}
	for y := 0; y < 6; y += 2 {
		var b strings.Builder
		for i, r := range "GITAPPHO" {
			var g strings.Builder
			for x := 0; x < 3; x++ {
				a, c := glyphs[r][y][x], glyphs[r][y+1][x]
				if a == '1' && c == '1' {
					g.WriteRune('█')
				} else if a == '1' {
					g.WriteRune('▀')
				} else if c == '1' {
					g.WriteRune('▄')
				} else {
					g.WriteRune(' ')
				}
			}
			b.WriteString(lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#49558B", Dark: colors[i]}).Render(g.String()))
			b.WriteString(" ")
		}
		b.WriteString(frame.Render(strings.Repeat("╱", max(0, width-32))))
		rows = append(rows, b.String())
	}
	return rows
}
func description(key string) string {
	switch key {
	case "save":
		return "Review, commit and optionally upload."
	case "update":
		return "Compare and synchronise safely."
	case "new":
		return "Create a branch or switch context."
	case "combine":
		return "Merge, rebase or open a pull request."
	case "fix":
		return "Resolve conflicts and recover work."
	}
	return "Open the guarded Git workflow."
}
func (m model) View() string {
	w, h := m.width-2, m.height-1
	if m.width == 0 {
		w = 76
	}
	if m.height == 0 {
		h = 24
	}
	w = max(1, min(120, w))
	h = max(1, h)
	if m.flow != nil {
		return m.workflowView(w, h)
	}
	if w < 20 || h < 7 {
		return brand.Render(fit("gitappho · resize", w))
	}
	rows := []string{}
	if h >= 16 {
		rows = append(rows, logo(w)...)
	} else {
		rows = append(rows, brand.Render("gitappho."))
	}
	rows = append(rows, muted.Render(fit("STUDIO  /  VERSION CONTROL REIMAGINED", w)))
	if m.loading {
		rows = append(rows, "", brand.Render(fit("◌ Inspecting repository…", w)))
		return strings.Join(rows, "\n")
	}
	status := brand
	if m.data.Working != "Clean" {
		status = warn
	}
	if len(m.data.Operation) > 0 || m.data.Blocked != "" {
		status = warn
	}
	rows = append(rows, brand.Render(fit(m.data.Project+"  /  "+m.data.Branch, w)), status.Render(fit(m.data.Working+" · "+m.data.Connection, w)))
	if len(m.data.Operation) > 0 {
		rows = append(rows, warn.Render(fit("Paused: "+strings.Join(m.data.Operation, ", "), w)))
	}
	if m.data.Blocked != "" {
		rows = append(rows, warn.Render(fit(m.data.Blocked, w)), muted.Render(fit("F5 retry · Esc exit", w)))
		return strings.Join(rows[:min(len(rows), h)], "\n")
	}
	if h >= 19 {
		rows = append(rows, "")
	}
	footer := "↑↓ Move  ·  Enter Open  ·  Ctrl+P Search  ·  Tab View  ·  Esc Back"
	if w < 66 {
		footer = "↑↓ Move  Enter Open  ^P Search  Tab"
	}
	if m.pending != nil {
		footer = "Enter Open  ·  Esc Back"
	}
	room := max(1, h-len(rows)-1)
	if m.note != "" && room >= 5 {
		room--
	}
	// Wide terminals get a live contextual rail. Compact VS Code panels stack naturally.
	wide := w >= 86 && room >= 8 && m.page == "home" && m.pending == nil
	left := w
	if wide {
		left = (w - 2) * 57 / 100
	}
	inner := max(1, left-4)
	boxed := room >= 4
	budget := room
	if boxed {
		budget -= 2
	} else {
		inner = left
	}
	content := []string{}
	label := "01 / NEXT MOVE"
	if m.pending != nil {
		label = "OPEN WORKFLOW"
		content = append(content, brand.Render(fit(m.pending.Label, inner)), muted.Render(fit("Review and approve here in Studio.", inner)))
	} else if m.page == "history" {
		label = "02 / COMMIT GRAPH"
		for _, s := range m.data.History {
			content = append(content, muted.Render(fit(s, inner)))
		}
		if len(content) == 0 {
			content = append(content, muted.Render(fit("No commits found.", inner)))
		}
	} else {
		if m.page == "search" {
			label = "03 / COMMAND PALETTE"
			ti := m.input
			ti.Width = max(1, inner-4)
			ti.Placeholder = fit("Search Git actions…", max(1, inner-4))
			content = append(content, ti.View(), muted.Render(fit(fmt.Sprintf("%d matching / %d actions", len(m.list()), len(m.data.Actions)), inner)))
		}
		list := m.list()
		n := max(1, budget-len(content))
		if m.page == "home" && budget >= 10 && !wide {
			n = 5
		}
		start := max(0, m.cursor-n+1)
		end := min(len(list), start+n)
		for i := start; i < end; i++ {
			a := list[i]
			s := "  " + a.Label
			if a.Blocked != "" {
				s += " · blocked"
			}
			if i == m.cursor {
				content = append(content, selected.Render(pad(fit("❯ "+strings.TrimSpace(s), inner), inner)))
			} else {
				content = append(content, muted.Render(fit(s, inner)))
			}
		}
		if len(list) == 0 {
			content = append(content, muted.Render(fit("No matching actions.", inner)))
		}
		if m.page == "home" && m.cursor < len(list) && len(content) < budget {
			a := list[m.cursor]
			detail := description(a.Key)
			if a.Blocked != "" {
				detail = a.Blocked
			}
			content = append(content, brand.Render(fit(detail, inner)))
		}
	}
	content = content[:min(len(content), budget)]
	body := ""
	if boxed {
		for i := range content {
			content[i] = " " + content[i] + " "
		}
		body = panel(label, content, left)
	} else {
		body = strings.Join(content, "\n")
	}
	if wide {
		right := w - left - 2
		ri := right - 4
		rail := []string{brand.Render(fit("WORKSPACE", ri)), muted.Render(fit(fmt.Sprintf("Saved work: %d", m.data.Stash), ri)), muted.Render(fit(fmt.Sprintf("Actions: %d", len(m.data.Actions)), ri)), "", violet.Render(fit("RECENT COMMITS", ri))}
		for _, s := range m.data.History {
			if len(rail) >= budget {
				break
			}
			rail = append(rail, muted.Render(fit(s, ri)))
		}
		rail = rail[:min(len(rail), budget)]
		for i := range rail {
			rail[i] = " " + rail[i] + " "
		}
		body = lipgloss.JoinHorizontal(lipgloss.Top, body, "  ", panel("CONTEXT", rail, right))
	}
	rows = append(rows, strings.Split(body, "\n")...)
	if m.note != "" && len(rows) < h-1 {
		rows = append(rows, warn.Render(fit(m.note, w)))
	}
	if len(rows) < h {
		rows = append(rows, muted.Render(fit(footer, w)))
	}
	return strings.Join(rows[:min(h, len(rows))], "\n")
}
func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "Usage: gitappho-studio CORE BRIDGE")
		os.Exit(2)
	}
	py, e := exec.LookPath("python3")
	if e != nil {
		fmt.Fprintln(os.Stderr, "Python 3 required")
		os.Exit(1)
	}
	core, e := filepath.Abs(os.Args[1])
	if e != nil {
		os.Exit(1)
	}
	bridge, e := filepath.Abs(os.Args[2])
	if e != nil {
		os.Exit(1)
	}
	ti := textinput.New()
	ti.Placeholder = "Search stash, rebase, undo…"
	ti.CharLimit = 120
	ti.Width = 40
	m := model{core: core, bridge: bridge, python: py, input: ti, page: "home", loading: true}
	if _, e := tea.NewProgram(m, tea.WithAltScreen()).Run(); e != nil {
		fmt.Fprintln(os.Stderr, "Studio could not run; use gitappho classic.")
		os.Exit(1)
	}
}
