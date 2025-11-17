  **Dependency graph visualizer**
   
  "-p" "--package-name" "Name of the package to analyze (required)"
  
  "-r" "--repo" "Repository URL or path to test repository (optional when --test-file is used)"
  
  "--test-file" "Path to test graph file (optional)"
  
  "-m" "--repo-mode" "Mode of working with test repo."
  
  "-v" "--version" "Package version to analyze (semver or 'latest'). Default: latest"
  
  "-o" "--output" "Generated image filename (.png, .svg). Default: dep_graph.png"
  
  "-f" "--filter" "Substring to filter packages by name (optional)"
  
  "--reverse" "Show reverse dependencies for the specified package"
  
  "--verbose" "Verbose mode (prints extra diagnostics)"
