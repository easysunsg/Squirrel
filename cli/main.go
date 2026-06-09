package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"

	"github.com/spf13/cobra"
)

type Item struct {
	Title        string `json:"title"`
	SpaceName    string `json:"spaceName"`
	Location     string `json:"location"`
	RemainingPct int    `json:"remainingPct"`
	ExpireDate   string `json:"expireDate"`
	Tag          string `json:"tag"`
	Count        int    `json:"count"`
	Unit         string `json:"unit"`
}

type itemsResponse struct {
	Items []Item `json:"items"`
}

var baseURL string

func apiURL(path string) string {
	if baseURL == "" {
		baseURL = os.Getenv("SQUIRREL_API_URL")
	}
	if baseURL == "" {
		baseURL = "http://localhost:8000"
	}
	return baseURL + path
}

func request(method string, path string, body any, out any) error {
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(raw)
	}
	req, err := http.NewRequest(method, apiURL(path), reader)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	raw, _ := io.ReadAll(res.Body)
	if res.StatusCode >= 300 {
		return fmt.Errorf("%s", string(raw))
	}
	if out != nil {
		return json.Unmarshal(raw, out)
	}
	return nil
}

func renderItems(items []Item) {
	if len(items) == 0 {
		fmt.Println("没有找到符合条件的库存。")
		return
	}
	for _, item := range items {
		fmt.Printf("%s x%d%s | %s | %s/%s | 剩余 %d%% | 到期 %s\n", item.Title, item.Count, item.Unit, item.Tag, item.SpaceName, item.Location, item.RemainingPct, item.ExpireDate)
	}
}

func main() {
	root := &cobra.Command{
		Use:   "squirrel",
		Short: "Squirrel CLI",
	}
	root.PersistentFlags().StringVar(&baseURL, "api", "", "Squirrel service URL")

	add := &cobra.Command{
		Use:   "add [text]",
		Short: "闪电录入库存",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var result itemsResponse
			if err := request("POST", "/api/cli/add", map[string]string{"text": strings.Join(args, " ")}, &result); err != nil {
				return err
			}
			fmt.Printf("已录入 %d 件物品：\n", len(result.Items))
			renderItems(result.Items)
			return nil
		},
	}

	var status string
	list := &cobra.Command{
		Use:   "list",
		Short: "列出库存",
		RunE: func(cmd *cobra.Command, args []string) error {
			var result itemsResponse
			if err := request("GET", "/api/items?status="+status, nil, &result); err != nil {
				return err
			}
			renderItems(result.Items)
			return nil
		},
	}
	list.Flags().StringVar(&status, "status", "all", "all, danger, low, full")

	clearExpired := false
	clear := &cobra.Command{
		Use:   "clear",
		Short: "清理库存",
		RunE: func(cmd *cobra.Command, args []string) error {
			if !clearExpired {
				return fmt.Errorf("当前仅支持 --expired")
			}
			var result map[string]any
			if err := request("DELETE", "/api/items/expired", nil, &result); err != nil {
				return err
			}
			fmt.Printf("已清理 %.0f 条告急/过期记录。\n", result["removed"])
			return nil
		},
	}
	clear.Flags().BoolVar(&clearExpired, "expired", false, "清理告急/过期记录")

	export := &cobra.Command{
		Use:   "export",
		Short: "导出 Markdown 报告",
		RunE: func(cmd *cobra.Command, args []string) error {
			var result map[string]any
			if err := request("POST", "/api/export?format=md", nil, &result); err != nil {
				return err
			}
			fmt.Printf("Markdown 库存报告已生成：%s\n", result["path"])
			return nil
		},
	}

	root.AddCommand(add, list, clear, export)
	if err := root.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
