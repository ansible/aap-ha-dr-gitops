// Offline evaluator for the Go-template subset used by this repository.
// It does not implement Git polling, cluster selection or controller reconciliation.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"text/template"
)

func render(value any, params map[string]any) (any, error) {
	switch v := value.(type) {
	case string:
		t, err := template.New("field").Option("missingkey=error").Funcs(template.FuncMap{
			"toJson": func(v any) (string, error) { b, err := json.Marshal(v); return string(b), err },
			"join": func(sep string, values []any) string { parts := make([]string, len(values)); for i, value := range values { parts[i] = fmt.Sprint(value) }; return strings.Join(parts, sep) },
			"concat": func(values ...[]any) []any { var result []any; for _, value := range values { result = append(result, value...) }; return result },
		}).Parse(v)
		if err != nil {
			return nil, err
		}
		var b bytes.Buffer
		if err := t.Execute(&b, params); err != nil {
			return nil, err
		}
		return b.String(), nil
	case map[string]any:
		out := map[string]any{}
		for k, child := range v {
			r, err := render(child, params)
			if err != nil {
				return nil, fmt.Errorf("%s: %w", k, err)
			}
			out[k] = r
		}
		return out, nil
	case []any:
		out := make([]any, len(v))
		for i, child := range v {
			r, err := render(child, params)
			if err != nil {
				return nil, err
			}
			out[i] = r
		}
		return out, nil
	default:
		return v, nil
	}
}

func main() {
	var in struct {
		Value  any
		Params map[string]any
	}
	if err := json.NewDecoder(os.Stdin).Decode(&in); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	out, err := render(in.Value, in.Params)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := json.NewEncoder(os.Stdout).Encode(out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
