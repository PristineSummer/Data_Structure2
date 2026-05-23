# Data Structure Design

## 1. Objective and Tasks

The Data Strcture Design is a comprehensive software design training program. It encompasses problem analysis, overall architectural design, user interface (UI) design, basic programming skills, teamwork, and the cultivation of software engineering standards and scientific rigor.

## 2. Design Content

Please use your imagination and choose appropriate data structures and algorithms. It is crucial to understand that the core assessment of this project focuses on the application of data structures and algorithms.

## 3. Optional Topics

## Topic : Navigation System

A vehicle navigation system is a great assistant for driving in the city. It not only calculates the optimal route to a destination but also displays additional information near the current location, such as gas stations, restaurants, etc. Please design navigation software to implement the core functions of a navigation system.

- Target Users: Car drivers.
- Data Configuration: The map in the navigation system can be abstracted as a graph, where location information and path information correspond to vertices and edges, respectively. Please design an algorithm to generate simulated map data:
  - Randomly generate $N$ vertices on a 2D plane ( $N \geq 10000$ ), each representing a location on the map.
  - For each location $x$, randomly establish several edges connecting to locations near $x$. Each edge represents a path, and its length equals the 2D coordinate distance between the two vertices.
  - The simulated data must ensure that the generated graph is a **connected graph** and that there are no unreasonable intersections between roads.

- Functional Requirements:
  - F1. Map Display: Input a coordinate and display the 100 nearest vertices and their associated edges. (For drawing with Visual C++ or Java, please search for relevant methods on Google/Baidu or refer to related books).
  - F2. Map Zoom: Implement zoom-in and zoom-out functionality. Hint: As the map zooms out, more points will appear on the screen, causing clutter. Consider displaying only one representative point within a unit area.
  - F3. Shortest Path: Specify any two locations, A and B, calculate the shortest path from A to B, and display the vertices and edges passed by this path.
  - F4. Traffic Simulation: Add two attributes to each edge: capacity $v$ (max cars the road can hold before saturation) and current vehicle count $n$ ( $n>v$ means overload). Assuming the road length is $L$, the travel time can be simulated as $c \cdot L \cdot f(n / v)$, where $c$ is a constant. $f(x)$ is a piecewise function: $f(x)=1$ when $x \leq$ threshold, and $f(x)=1+e^{x}$ when $x>$ threshold. Capacity $v$ and length $L$ are predefined fixed parameters. Simulate cars driving on the map (for simplicity, assume all cars traversing the same road take $c \cdot L \cdot f(n / v)$ ). Implement dynamic visualization of traffic flow: at any given time and coordinate, display all nearby paths and dynamically show their traffic volume (using different colors or other methods to distinguish traffic levels).
  - F5. Traffic-Aware Shortest Path: At any given time, specify locations A and B . Calculate the path with the shortest travel time based on the current traffic conditions, and display the corresponding optimal path (vertices and edges) on the interface.

## 4. Design Work Requirements

The implemented program must meet the following criteria:

1. User-Friendly Interface: Graphical User Interface (GUI) supporting mouse operations. Include reasonable prompts and menus. Illegal inputs should trigger proper exception warnings.
2. Physical Storage: Relevant data must be stored in data files. Your program must implement file Read/Write (I/O) operations.
3. Logical Structure: Adopt linear or non-linear data structures based on the problem's requirements. Except for a few specific topics, large data volume handling must be considered.

Submission Contents: Each group must submit the following materials:

- Source Code: Must be well-commented, strictly formatted, and modularized. Allowed languages: C++ / Java / Python / etc.
- Executable File: A runnable application.
- Defense Presentation (PPT).
- Course Design Report (Document): Each team, as a whole, must submit a report detailing the specific work you undertook. This is a crucial grading component:
  - Requirements Analysis: State the problem to be solved and the functions to be implemented.
  - Detailed Design: Include algorithm flowcharts, algorithm complexity analysis, and data structures used.
  - Software Testing: Include test data and test result records.
  - Conclusion: Problems encountered and solutions; unresolved issues and future strategies; personal takeaways.
  - References: Mandatory! List textbooks, reference books, papers, or websites used, formatted according to academic standards.




