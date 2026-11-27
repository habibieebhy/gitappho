package main

import (
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/lipgloss"
	"strings"
	"testing"
)

func TestIdentityFitsTerminal(t *testing.T) {
	for _, w := range []int{22, 32, 42, 60, 80, 88, 100, 125} {
		for _, h := range []int{8, 12, 18, 24, 40} {
			for _, page := range []string{"home", "search", "history"} {
				ti := textinput.New()
				ti.SetValue("stash")
				if page != "search" {
					ti.SetValue("")
				}
				m := model{width: w, height: h, page: page, input: ti, data: snapshot{Project: "A long project name", Branch: "feature/a-long-branch-name", Working: "Unfinished changes", Connection: "Registered / not verified", History: []string{"* 1234567 a long commit subject"}, Actions: []action{{Key: "save", Label: "Save my work"}, {Key: "update", Label: "Get the latest work"}, {Key: "new", Label: "Work on something new"}, {Key: "combine", Label: "Combine my work"}, {Key: "fix", Label: "Fix a problem"}, {Key: "stash", Label: "Set aside unfinished work", Words: "stash"}}}}
				v := m.View()
				lines := strings.Split(v, "\n")
				if len(lines) > h-1 {
					t.Fatalf("height %d/%d page %s", len(lines), h, page)
				}
				for _, line := range lines {
					if lipgloss.Width(line) > w-2 {
						t.Fatalf("width %d/%d page %s: %q", lipgloss.Width(line), w, page, line)
					}
				}
			}
		}
	}
}
func TestIdentityShowsActions(t *testing.T) {
	m := model{width: 85, height: 30, page: "home", data: snapshot{Project: "repo", Branch: "main", Working: "Clean", Actions: []action{{Key: "save", Label: "Save my work"}, {Key: "fix", Label: "Fix a problem"}}}}
	v := m.View()
	for _, s := range []string{"Save my work", "Fix a problem", "NEXT MOVE"} {
		if !strings.Contains(v, s) {
			t.Fatalf("missing %s", s)
		}
	}
}
