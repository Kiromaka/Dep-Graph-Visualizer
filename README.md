  # **Dependency graph visualizer**

  # CLI Визуализатор графоф зависимости.

  На данный момент функции - парсинг аргументов и обработка ошибок с ожидаемым входом адреса репозитории.
   
  "-p" "--package-name" "Name of the package to analyze (required)"
  
  "-r" "--repo" "Repository URL or path to test repository (optional when --test-file is used)"
  
  "--test-file" "Path to test graph file (optional)"
  
  "-m" "--repo-mode" "Mode of working with test repo."
  
  "-v" "--version" "Package version to analyze (semver or 'latest'). Default: latest"
  
  "-o" "--output" "Generated image filename (.png, .svg). Default: dep_graph.png"
  
  "-f" "--filter" "Substring to filter packages by name (optional)"
  
  example : python graph_wiz numpy github.com/numpy выведет адрес пакета. 
  
 
