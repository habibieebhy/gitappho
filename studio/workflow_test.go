package main

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"strings"
	"testing"
)

func TestWorkflowLayout(t *testing.T) {
	for _, w := range []int{22, 32, 38, 60, 80, 100, 125} {
		for _, h := range []int{8, 12, 15, 16, 18, 24, 40} {
			for _, mode := range []string{"choice", "text", "confirm", "done", "running"} {
				f := newWorkflow(action{Label: "Save my work"})
				f.append(strings.Repeat("A long output line abcdefghijklmnopqrstuvwxyz\n", 30))
				if mode == "done" {
					f.finished = true
				} else if mode != "running" {
					f.prompt = &workflowEvent{Mode: mode, Text: "Review files before committing changes. This prompt may be quite long.", Options: []option{{Value: "CANCEL", Label: "Cancel / keep current state"}, {Value: "COMMIT", Label: "Approve — COMMIT"}}}
					f.input.SetValue("test commit")
				}
				m := model{flow: f, width: w, height: h}
				v := m.View()
				lines := strings.Split(v, "\n")
				if len(lines) > h-1 {
					t.Fatalf("height %d > %d mode %s", len(lines), h-1, mode)
				}
				for _, l := range lines {
					if lipgloss.Width(l) > w-2 {
						t.Fatalf("width %d > %d mode %s", lipgloss.Width(l), w-2, mode)
					}
				}
				if w >= 60 && h >= 24 && mode == "confirm" && !strings.Contains(v, "Cancel / keep current state") {
					t.Fatal("missing safe default")
				}
			}
		}
	}
}
func TestNativePromptTransition(t *testing.T) {
	f := newWorkflow(action{Label: "Save"})
	m := model{flow: f, width: 80, height: 25} // a prompt event cannot execute an action; cancellation remains selected.
	n, _ := m.updateWorkflow(workflowMessage{event: workflowEvent{Kind: "prompt", Mode: "confirm", Text: "Review", Options: []option{{Value: "CANCEL", Label: "Cancel"}, {Value: "COMMIT", Label: "Approve"}}}})
	a := n.(model)
	if a.flow.prompt == nil || a.flow.cursor != 0 {
		t.Fatal("unsafe selection")
	}
	n, _ = a.updateWorkflow(tea.KeyMsg{Type: tea.KeyDown})
	if n.(model).flow.cursor != 1 {
		t.Fatal("selection not updated")
	}
}
