# Graph Report - .  (2026-05-05)

## Corpus Check
- 193 files · ~137,778 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1268 nodes · 1880 edges · 96 communities detected
- Extraction: 68% EXTRACTED · 32% INFERRED · 0% AMBIGUOUS · INFERRED: 596 edges (avg confidence: 0.67)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 92|Community 92]]
- [[_COMMUNITY_Community 93|Community 93]]
- [[_COMMUNITY_Community 94|Community 94]]
- [[_COMMUNITY_Community 95|Community 95]]

## God Nodes (most connected - your core abstractions)
1. `Indicators` - 53 edges
2. `HistoricalFetcher` - 43 edges
3. `FundamentalGraphs` - 42 edges
4. `MarketMovers` - 32 edges
5. `Minds` - 30 edges
6. `Overview` - 30 edges
7. `Markets` - 28 edges
8. `Screener` - 28 edges
9. `cn()` - 25 edges
10. `Streamer` - 24 edges

## Surprising Connections (you probably didn't know these)
- `market_movers_scraper()` --calls--> `MarketMovers`  [INFERRED]
  tests\test_market_movers.py → tradingview_scraper\symbols\market_movers.py
- `A class to handle bulk historical data fetching from TradingView via WebSocket p` --uses--> `DataNotFoundError`  [INFERRED]
  tradingview_scraper\symbols\historical.py → tradingview_scraper\symbols\exceptions.py
- `Fetches historical OHLC data with pagination.          Args:             exch` --uses--> `DataNotFoundError`  [INFERRED]
  tradingview_scraper\symbols\historical.py → tradingview_scraper\symbols\exceptions.py
- `Sorts the hashed map chronologically and trims to the requested date if necessar` --uses--> `DataNotFoundError`  [INFERRED]
  tradingview_scraper\symbols\historical.py → tradingview_scraper\symbols\exceptions.py
- `Exports data to a specified format (JSON or CSV).          Args:             jso` --uses--> `DataNotFoundError`  [INFERRED]
  tradingview_scraper\symbols\stream\streamer.py → tradingview_scraper\symbols\exceptions.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.03
Nodes (100): CandleDB, CandleDB — SQLite persistent store for OHLCV candle data.  Location: Trading-P, Record the wall-clock time of the last successful TV fetch., Return candles sorted ASCENDING by timestamp.         If count is given, return, Return all candles with ts >= since_ts, sorted ascending.         Used by the d, Most recent candle Unix timestamp, or None if no data exists., Oldest candle Unix timestamp, or None if no data exists., Number of stored candles for a particular series. (+92 more)

### Community 1 - "Community 1"
Cohesion: 0.04
Nodes (51): DataCollector, Continuous WebSocket listener for multiple symbols.     Emits raw candle data i, Runs the streaming generator in a synchronous thread loop with auto-reconnect., DataNotFoundError, Custom exception for when data is not found., Module providing a two function which return python generator contains trades re, Handles keyboard interrupt signals to gracefully close the WebSocket connection., signal_handler() (+43 more)

### Community 2 - "Community 2"
Cohesion: 0.04
Nodes (46): FundamentalGraphs, Module providing a function to scrape fundamental financial graphs data from Tra, Validate and format symbol.          Args:             symbol (str): The symbol, A class to scrape fundamental financial data for symbols from TradingView., Get comprehensive fundamental financial data for a symbol.          Args:, Get income statement data for a symbol.          Args:             symbol (str):, Get balance sheet data for a symbol.          Args:             symbol (str): Th, Get cash flow statement data for a symbol.          Args:             symbol (st (+38 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (51): Configuration file for the Sphinx documentation builder.  For the full list of b, Skip autodoc for __init__ method., skip(), Exception, Ideas, Module providing a function to scrape published user ideas about a symbol., Scrapes trading ideas (popular or recent) for a specified symbol and page from T, get_indicators() (+43 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (34): Minds, Module providing a function to scrape Minds community discussions from TradingVi, Parse a single mind item.          Args:             item (Dict): Raw mind item, Get Minds discussions for a symbol.          Args:             symbol (str): The, A class to scrape Minds community discussions and insights from TradingView., Get all available Minds discussions for a symbol with pagination.          Args:, Validate and format symbol.          Args:             symbol (str): The symbol, Validate sort option.          Args:             sort (str): The sort option to (+26 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (33): Overview, Module providing a function to scrape symbol overview data from TradingView., A class to scrape comprehensive overview data for symbols from TradingView., Validate and format symbol.          Args:             symbol (str): The symbol, Get comprehensive overview data for a symbol.          Args:             symbol, Get basic profile information for a symbol.          Args:             symbol (s, Get market statistics for a symbol.          Args:             symbol (str): The, Get financial metrics for a symbol.          Args:             symbol (str): The (+25 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (30): MarketMovers, Module providing a function to scrape market movers data (gainers, losers, penny, Validate if the category is supported for the given market.          Args:, Build the payload for the TradingView scanner API.          Args:             ma, A class to scrape market movers data from TradingView.      This class provides, Get filter conditions based on market and category.          Args:             m, Get sort configuration based on category.          Args:             category (s, Get the appropriate scanner URL for the market.          Args:             marke (+22 more)

### Community 7 - "Community 7"
Cohesion: 0.06
Nodes (31): Markets, Module providing a function to scrape market overview data (top stocks, indices,, Build the payload for the scanner API.          Args:             filters (List[, A class to scrape market overview data from TradingView.      This class provide, Get top stocks by specified criteria.          Args:             market (str): T, Validate if the market is supported.          Args:             market (str): Th, Validate and convert sort criteria.          Args:             sort_by (str): Th, Test getting top stocks with no data. (+23 more)

### Community 8 - "Community 8"
Cohesion: 0.06
Nodes (31): Module providing a function to screen stocks, crypto, forex, and other markets w, Validate if the market is supported.          Args:             market (str): Th, Get default columns based on market type.          Args:             market (str, A class to screen financial instruments from TradingView with custom filters., Build the payload for the scanner API.          Args:             filters (List[, Screen financial instruments based on custom filters.          Args:, Screener, Test screening with filters. (+23 more)

### Community 9 - "Community 9"
Cohesion: 0.04
Nodes (33): detect_all_consolidations(), Consolidation detector (price action based), Detect consolidation zones.     A zone is active when (high - low) / close < ran, DataFetcher, DataFetcher — in-memory candle store for the multi-timeframe engine.  Optimizati, Add a closed candle.         Format: {timestamp, open, high, low, close, is_clos, Fast O(1) latest close price lookup., Returns a pandas DataFrame for the timeframe — validated before construction. (+25 more)

### Community 10 - "Community 10"
Cohesion: 0.05
Nodes (25): AlertDialogFooter(), AlertDialogHeader(), Badge(), BreadcrumbEllipsis(), BreadcrumbSeparator(), Calendar(), CommandShortcut(), ContextMenuShortcut() (+17 more)

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (17): Config, DashboardLauncher, _find_node_exec(), _http_ok(), _kill_pid(), _kill_port(), Dashboard Launcher — TradingView Scraper =======================================, Thread-safe log call via root.after. (+9 more)

### Community 12 - "Community 12"
Cohesion: 0.09
Nodes (25): CalendarScraper, DividendEvent, EarningsEvent, Module providing a function to scrape dividend and earnings of a specific market, A class used to scrape dividend and earnings events from the TradingView event c, Scrapes dividends events from the TradingView event calendar.          Args:, Represents a dividend event for a financial asset.      Attributes:         full, Scrapes earnings events from the TradingView event calendar.          Args: (+17 more)

### Community 13 - "Community 13"
Cohesion: 0.09
Nodes (21): Prepends the message with a header indicating its length.          Args:, Constructs a message in JSON format.          Args:             func (str): T, Creates a complete message with a header and a JSON body.          Args:, Sends a message to the WebSocket server.          Args:             func (str, Returns a generator that yields OHLC data for a specified symbol in real-time., Initializes the WebSocket sessions for quotes and charts., Returns the fields to be set for the quote session.                  Returns:, Adds the specified symbol to the quote and chart sessions. (+13 more)

### Community 14 - "Community 14"
Cohesion: 0.09
Nodes (18): NewsScraper, Module providing a function to scrape published news about a symbol., Scrapes news headlines for a specified symbol from a given exchange, provider, o, Load languages from a specified file.          Returns:             list: A list, Load exchanges from a specified file.          Returns:             list: A list, Load news providers from a specified file.          Returns:             list: A, Load areas from a specified file.          Returns:             list: A list of, Scrapes news content from a TradingView article based on the provided story path (+10 more)

### Community 15 - "Community 15"
Cohesion: 0.1
Nodes (18): Export scraped data to file.          Args:             data (Dict): The data to, Extract trading ideas from TradingView for a specified symbol over a range of pa, Export scraped data to file.          Args:             data (List[Dict]): The d, Export scraped data to file.          Args:             data (List[Dict]): The d, Export scraped data to file.          Args:             data (List[Dict]): The d, Export scraped data to file.          Args:             data (Dict): The data to, Export screened data to file.          Args:             data (List[Dict]): The, Exports data to a specified format (JSON or CSV).          Args:             jso (+10 more)

### Community 16 - "Community 16"
Cohesion: 0.08
Nodes (11): DataAggregator, Subscribes to VALIDATED_CANDLE events on the base timeframe (e.g., 1m).     Aggr, Calculate the boundary start time for a given timestamp and TF., EventEngine, Emits an event to all subscribers asynchronously., A simple pub/sub Event Engine for the trading pipeline.     Allows decoupling of, FeatureExtractor, Subscribes to VALIDATED_CANDLE.      Maintains a rolling window of 3 candles to (+3 more)

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (18): detect_breakout(), Breakout detector — optimized.  Changes:   - Added ATR-based expansion check: br, Detects an aggressive breakout candle.      Rules (all must pass):       1. Clos, _build_path(), _calc_rr(), _find_historical_tp(), generate_scenarios(), _no_trade() (+10 more)

### Community 18 - "Community 18"
Cohesion: 0.13
Nodes (12): is_valid_event(), is_valid_time(), is_valid_timeframe(), Check if timeframe is allowed for alerts., Check if the event is stringently breakout or trap., Check if current time is between 11:00 and 22:00 IST., AlertManager, Alert Manager — optimized.  Changes:   - sent_alerts uses collections.deque(maxl (+4 more)

### Community 19 - "Community 19"
Cohesion: 0.11
Nodes (9): Initialize the FundamentalGraphs scraper.          Args:             export_resu, Initialize the MarketMovers scraper.          Args:             export_result (b, Initialize the Markets scraper.          Args:             export_result (bool):, Initialize the Minds scraper.          Args:             export_result (bool): W, Initialize the Overview scraper.          Args:             export_result (bool), Initialize the Screener.          Args:             export_result (bool): Whethe, Initialize the SymbolMarkets scraper.          Args:             export_result (, generate_user_agent() (+1 more)

### Community 20 - "Community 20"
Cohesion: 0.24
Nodes (10): hexAlpha(), worldToCanvas(), drawCandles(), drawConsolidations(), drawCrosshair(), drawGrid(), drawNowLine(), drawScenarios() (+2 more)

### Community 21 - "Community 21"
Cohesion: 0.15
Nodes (5): ChartPage(), getSymbolPrecision(), btnStyle(), ChartBoxContainer(), useChartMemory()

### Community 22 - "Community 22"
Cohesion: 0.16
Nodes (4): classifySwings(), exportSwingsAsCsv(), loadSwingsFromMemory(), selectActiveSwings()

### Community 23 - "Community 23"
Cohesion: 0.21
Nodes (7): consolidation_boxes(), ConsolidationCNN, get_instance(), NNPredictor, Detect consolidation boxes.     df must have columns ['open','high','low','clos, get_nn_refined_zones(), Return consolidation zones enriched with NN-predicted refined box coordinates.

### Community 24 - "Community 24"
Cohesion: 0.18
Nodes (11): display_and_select_indicator(), fetch_indicator_metadata(), fetch_tradingview_indicators(), prepare_indicator_metadata(), Module providing utility functions for validating exchange symbols and fetching, Display a list of indicators and prompt the user to select one.      This functi, Validate one or more exchange symbols.      This function checks whether the pro, Fetch metadata for a TradingView indicator based on its script ID and version. (+3 more)

### Community 25 - "Community 25"
Cohesion: 0.18
Nodes (0): 

### Community 26 - "Community 26"
Cohesion: 0.36
Nodes (7): assertStrictOrder(), dedupeAfterTimeTransform(), dedupeRaw(), mapOverlayTime(), prepareChartData(), toDayString(), toWeekString()

### Community 27 - "Community 27"
Cohesion: 0.33
Nodes (7): Toaster(), addToRemoveQueue(), dispatch(), genId(), reducer(), toast(), useToast()

### Community 28 - "Community 28"
Cohesion: 0.46
Nodes (7): drawGrid(), drawLabel(), drawLoading(), drawPriceAxis(), drawTimeAxis(), drawVolume(), renderCandleChart()

### Community 29 - "Community 29"
Cohesion: 0.29
Nodes (1): WebpackHealthPlugin

### Community 30 - "Community 30"
Cohesion: 0.4
Nodes (2): App(), useHash()

### Community 31 - "Community 31"
Cohesion: 0.4
Nodes (2): _buildMockCandles(), _getMockCandlesWithTickUpdate()

### Community 32 - "Community 32"
Cohesion: 0.47
Nodes (3): fetchIndicators(), fetchLiveCandles(), resolveSymbol()

### Community 33 - "Community 33"
Cohesion: 0.33
Nodes (2): Pipeline, Orchestrates the entire Trading Data Pipeline.

### Community 34 - "Community 34"
Cohesion: 0.47
Nodes (4): drawAll(), drawChart(), drawGrid(), pollData()

### Community 35 - "Community 35"
Cohesion: 0.4
Nodes (4): renderConsolidation(), drawSpatialGrid(), renderEngine(), renderTimeframe()

### Community 36 - "Community 36"
Cohesion: 0.4
Nodes (0): 

### Community 37 - "Community 37"
Cohesion: 0.5
Nodes (0): 

### Community 38 - "Community 38"
Cohesion: 0.5
Nodes (0): 

### Community 39 - "Community 39"
Cohesion: 0.5
Nodes (0): 

### Community 40 - "Community 40"
Cohesion: 0.67
Nodes (1): Setup configuration for tradingview-scraper package.

### Community 41 - "Community 41"
Cohesion: 0.67
Nodes (0): 

### Community 42 - "Community 42"
Cohesion: 0.67
Nodes (1): ChartCanvas()

### Community 43 - "Community 43"
Cohesion: 0.67
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 0.67
Nodes (0): 

### Community 45 - "Community 45"
Cohesion: 0.67
Nodes (0): 

### Community 46 - "Community 46"
Cohesion: 0.67
Nodes (2): detect_retracement(), Detects simple retracement (pullback).     If bullish direction: look for a shor

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (0): 

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (0): 

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (0): 

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (0): 

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (0): 

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (0): 

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (0): 

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (0): 

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (0): 

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (0): 

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (0): 

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (0): 

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (0): 

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (0): 

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (0): 

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (0): 

### Community 78 - "Community 78"
Cohesion: 1.0
Nodes (0): 

### Community 79 - "Community 79"
Cohesion: 1.0
Nodes (0): 

### Community 80 - "Community 80"
Cohesion: 1.0
Nodes (0): 

### Community 81 - "Community 81"
Cohesion: 1.0
Nodes (0): 

### Community 82 - "Community 82"
Cohesion: 1.0
Nodes (0): 

### Community 83 - "Community 83"
Cohesion: 1.0
Nodes (0): 

### Community 84 - "Community 84"
Cohesion: 1.0
Nodes (0): 

### Community 85 - "Community 85"
Cohesion: 1.0
Nodes (0): 

### Community 86 - "Community 86"
Cohesion: 1.0
Nodes (0): 

### Community 87 - "Community 87"
Cohesion: 1.0
Nodes (0): 

### Community 88 - "Community 88"
Cohesion: 1.0
Nodes (0): 

### Community 89 - "Community 89"
Cohesion: 1.0
Nodes (0): 

### Community 90 - "Community 90"
Cohesion: 1.0
Nodes (0): 

### Community 91 - "Community 91"
Cohesion: 1.0
Nodes (0): 

### Community 92 - "Community 92"
Cohesion: 1.0
Nodes (0): 

### Community 93 - "Community 93"
Cohesion: 1.0
Nodes (0): 

### Community 94 - "Community 94"
Cohesion: 1.0
Nodes (0): 

### Community 95 - "Community 95"
Cohesion: 1.0
Nodes (0): 

## Knowledge Gaps
- **262 isolated node(s):** `Dashboard Launcher — TradingView Scraper =======================================`, `Return full path to yarn.cmd or npm.cmd, whichever is preferred + available.`, `Kill any process currently LISTENING on the given port.`, `Thread-safe log call via root.after.`, `Stream subprocess stdout into the log window (runs in daemon thread).` (+257 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 47`** (2 nodes): `FeaturesSection()`, `FeaturesSection.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (2 nodes): `Footer()`, `Footer.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (2 nodes): `Hero()`, `Hero.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (2 nodes): `Navbar()`, `Navbar.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (2 nodes): `PricingSection()`, `PricingSection.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (2 nodes): `TopStories()`, `TopStories.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (2 nodes): `InfiniteCanvasPage()`, `InfiniteCanvasPage.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (2 nodes): `ChartToolbar()`, `ChartToolbar.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (2 nodes): `LayoutSelector()`, `LayoutSelector.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (2 nodes): `useCarousel()`, `carousel.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (2 nodes): `Toaster()`, `sonner.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (2 nodes): `useCanvasStore.js`, `generateId()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (2 nodes): `LayerController()`, `LayerController.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `craco.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `tailwind.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `index.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `accordion.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `alert.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `button.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `card.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `checkbox.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `collapsible.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `input.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `label.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `popover.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `progress.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `select.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `separator.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `switch.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 78`** (1 nodes): `table.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 79`** (1 nodes): `tabs.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 80`** (1 nodes): `textarea.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 81`** (1 nodes): `toast.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 82`** (1 nodes): `toggle.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 83`** (1 nodes): `tooltip.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 84`** (1 nodes): `mockData.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 85`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 86`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 87`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 88`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 89`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 90`** (1 nodes): `vite.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 91`** (1 nodes): `main.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 92`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 93`** (1 nodes): `tradingview_scraper.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 94`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 95`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Streamer` connect `Community 1` to `Community 15`?**
  _High betweenness centrality (0.138) - this node is a cross-community bridge._
- **Why does `save_json_file()` connect `Community 15` to `Community 12`, `Community 14`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Why does `save_csv_file()` connect `Community 15` to `Community 12`, `Community 14`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Are the 42 inferred relationships involving `Indicators` (e.g. with `TestIndicators` and `Setup method to create an Indicators instance.`) actually correct?**
  _`Indicators` has 42 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `HistoricalFetcher` (e.g. with `Trading Intelligence API — optimized.  Changes:   - asyncio.Lock guards all s` and `sha256(symbol:tf:tStart:tEnd:pH:pL) → first 16 hex chars.`) actually correct?**
  _`HistoricalFetcher` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `FundamentalGraphs` (e.g. with `TestFundamentalGraphs` and `Fixture to create an instance of FundamentalGraphs for testing.`) actually correct?**
  _`FundamentalGraphs` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `MarketMovers` (e.g. with `TestMarketMovers` and `Fixture to create an instance of MarketMovers for testing.`) actually correct?**
  _`MarketMovers` has 21 INFERRED edges - model-reasoned connections that need verification._