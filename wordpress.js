/* ========================================
   Word_TO_WP_Manual - greg crouch
   ======================================== */

/* Accessibility behaviors (WCAG 2.1 AA) */
(function () {
  // Check if user prefers reduced motion
  var prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function initManual() {
    var grids = document.querySelectorAll(".manual-grid");
    if (!grids.length) {
      // If not found immediately, try again after a short delay for WordPress compatibility
      setTimeout(function() {
        var retryGrids = document.querySelectorAll(".manual-grid");
        if (retryGrids.length) {
          processManualGrids(retryGrids);
        }
      }, 100);
      return;
    }
    processManualGrids(grids);
  }

  function normalizeListStyles(manual) {
    if (!manual) return;
    var classToStyle = {
      "list-decimal": "decimal",
      "list-alpha-lower": "lower-alpha",
      "list-alpha-upper": "upper-alpha",
      "list-roman-lower": "lower-roman",
      "list-roman-upper": "upper-roman"
    };
    var styleToClass = {
      "decimal": "list-decimal",
      "lower-alpha": "list-alpha-lower",
      "upper-alpha": "list-alpha-upper",
      "lower-roman": "list-roman-lower",
      "upper-roman": "list-roman-upper"
    };
    var typeToStyle = {
      "1": "decimal",
      "a": "lower-alpha",
      "A": "upper-alpha",
      "i": "lower-roman",
      "I": "upper-roman"
    };
    var styleToType = {
      "decimal": "1",
      "lower-alpha": "a",
      "upper-alpha": "A",
      "lower-roman": "i",
      "upper-roman": "I"
    };

    var lists = manual.querySelectorAll("ol");
    for (var i = 0; i < lists.length; i++) {
      var ol = lists[i];
      var styleType = ol.getAttribute("data-list-style");
      if (!styleType) {
        for (var cls in classToStyle) {
          if (ol.classList.contains(cls)) {
            styleType = classToStyle[cls];
            break;
          }
        }
      }
      if (!styleType) {
        var typeAttr = ol.getAttribute("type") || "";
        if (typeToStyle[typeAttr]) {
          styleType = typeToStyle[typeAttr];
        } else if (/^\d+$/.test(typeAttr)) {
          styleType = "decimal";
        }
      }
      if (!styleType) continue;

      ol.setAttribute("data-list-style", styleType);
      // Use setProperty with 'important' to override theme CSS !important rules
      ol.style.setProperty("list-style-type", styleType, "important");
      var clsName = styleToClass[styleType];
      if (clsName && !ol.classList.contains(clsName)) {
        ol.classList.add(clsName);
      }
      if (!ol.getAttribute("type") && styleToType[styleType]) {
        ol.setAttribute("type", styleToType[styleType]);
      }
    }
  }

  function processManualGrids(grids) {
    for (var g = 0; g < grids.length; g++) {
      var grid = grids[g];
      if (grid.dataset.gsppEnhanced === "1") continue;
      grid.dataset.gsppEnhanced = "1";

      // Scope class so CSS only targets real manuals; also allow layout flush
      grid.classList.add("gspp-manual");

      var manual = grid.querySelector(".manual");
      var toc = grid.querySelector(".manual-toc");
      if (!manual || !toc) continue;

      // Keep sticky TOC working even when outer wrappers clip overflow or use transforms.
      // MDN: position:sticky fails when ancestor has overflow:hidden/auto/scroll OR transform/filter/perspective.
      (function ensureStickyAncestors() {
        var node = grid;
        var depth = 0;

        // First pass: immediate fix
        while (node && node !== document.documentElement && depth < 15) {
          var style = window.getComputedStyle(node);
          if (style) {
            var overflow = style.overflow;
            var overflowY = style.overflowY;
            var overflowX = style.overflowX;
            var transform = style.transform;
            var filter = style.filter;
            var perspective = style.perspective;
            var willChange = style.willChange;

            if (overflow === "hidden" || overflow === "auto" || overflow === "scroll") {
              node.style.setProperty('overflow', 'visible', 'important');
            }
            if (overflowY === "hidden" || overflowY === "auto" || overflowY === "scroll") {
              node.style.setProperty('overflow-y', 'visible', 'important');
            }
            if (overflowX === "hidden" || overflowX === "auto" || overflowX === "scroll") {
              node.style.setProperty('overflow-x', 'visible', 'important');
            }
            // Clear transform/filter/perspective that break sticky positioning
            if (transform && transform !== "none") {
              node.style.setProperty('transform', 'none', 'important');
            }
            if (filter && filter !== "none") {
              node.style.setProperty('filter', 'none', 'important');
            }
            if (perspective && perspective !== "none") {
              node.style.setProperty('perspective', 'none', 'important');
            }
            if (willChange && willChange.indexOf("transform") !== -1) {
              node.style.setProperty('will-change', 'auto', 'important');
            }
          }
          node = node.parentElement;
          depth += 1;
        }

        // Second pass: delayed re-check + force TOC sticky
        setTimeout(function() {
          var node = grid;
          var depth = 0;
          while (node && node !== document.documentElement && depth < 15) {
            var style = window.getComputedStyle(node);
            if (style) {
              var overflow = style.overflow;
              var overflowY = style.overflowY;
              var overflowX = style.overflowX;
              if (overflow === "hidden" || overflow === "auto" || overflow === "scroll") {
                node.style.setProperty('overflow', 'visible', 'important');
              }
              if (overflowY === "hidden" || overflowY === "auto" || overflowY === "scroll") {
                node.style.setProperty('overflow-y', 'visible', 'important');
              }
              if (overflowX === "hidden" || overflowX === "auto" || overflowX === "scroll") {
                node.style.setProperty('overflow-x', 'visible', 'important');
              }
            }
            node = node.parentElement;
            depth += 1;
          }

          // Force TOC to be sticky
          toc.style.setProperty('position', 'sticky', 'important');
          toc.style.setProperty('top', '20px', 'important');
        }, 500);
      })();

      normalizeListStyles(manual);

      // Force list styles (Standard, Non-Nuclear)
      function forceListStyles() {
        // Force list types - ONLY use list-style-type, not shorthand
        manual.querySelectorAll('ol[type="a"], ol.list-alpha-lower, ol[data-list-style="lower-alpha"]').forEach(function(ol) {
          ol.style.setProperty('list-style-type', 'lower-alpha', 'important');
        });

        manual.querySelectorAll('ol[type="i"], ol.list-roman-lower, ol[data-list-style="lower-roman"]').forEach(function(ol) {
          ol.style.setProperty('list-style-type', 'lower-roman', 'important');
        });

        manual.querySelectorAll('ol[type="1"], ol.list-decimal, ol[data-list-style="decimal"]').forEach(function(ol) {
          ol.style.setProperty('list-style-type', 'decimal', 'important');
        });

        manual.querySelectorAll('ol[type="A"], ol.list-alpha-upper, ol[data-list-style="upper-alpha"]').forEach(function(ol) {
          ol.style.setProperty('list-style-type', 'upper-alpha', 'important');
        });

        manual.querySelectorAll('ol[type="I"], ol.list-roman-upper, ol[data-list-style="upper-roman"]').forEach(function(ol) {
          ol.style.setProperty('list-style-type', 'upper-roman', 'important');
        });
      }

      // Run immediately
      forceListStyles();

      // Run after short delay (theme might load CSS late)
      setTimeout(forceListStyles, 100);
      setTimeout(forceListStyles, 300);
      setTimeout(forceListStyles, 500);
      setTimeout(forceListStyles, 1000);

      // Run on window load (ensures all CSS is loaded)
      window.addEventListener('load', forceListStyles);

      var tocList = toc.querySelector("ul");
      var tocSearch = toc.querySelector(".manual-search-input, input[type='search']");
      var tocClear = toc.querySelector(".manual-search-clear");
      if (!tocList) continue;

      // WCAG 4.1.3: announce TOC filter results to screen readers
      if (!tocList.getAttribute("aria-live")) {
        tocList.setAttribute("aria-live", "polite");
      }

      // WordPress strips <input> tags from Custom HTML blocks.
      // If the search input is missing, create it from JS.
      if (!tocSearch) {
        var searchDiv = toc.querySelector(".manual-search");
        if (!searchDiv) {
          searchDiv = document.createElement("div");
          searchDiv.className = "manual-search";
          toc.insertBefore(searchDiv, tocList);
        }
        tocSearch = document.createElement("input");
        tocSearch.type = "text";
        tocSearch.className = "manual-search-input";
        tocSearch.placeholder = "Search headings and content...";
        tocSearch.setAttribute("aria-label", "Search table of contents");
        tocSearch.setAttribute("role", "searchbox");
        searchDiv.insertBefore(tocSearch, searchDiv.firstChild);
        if (!tocClear) {
          tocClear = document.createElement("button");
          tocClear.type = "button";
          tocClear.className = "manual-search-clear";
          tocClear.setAttribute("aria-label", "Clear search");
          tocClear.textContent = "X";
          searchDiv.appendChild(tocClear);
        }
      }

      /* ----- Process ALL headings for search and navigation ----- */
      var allHeadings = Array.prototype.slice.call(manual.querySelectorAll("h1, h2, h3, h4, h5, h6"));
      
      // Determine TOC depth from data attribute or default to 2 (H1-H2)
      var tocDepth = parseInt(grid.dataset.tocDepth || "2", 10);
      var headingOffset = parseInt(grid.dataset.headingOffset || "0", 10);
      if (isNaN(headingOffset)) headingOffset = 0;
      
      function getEffectiveLevel(heading) {
        var rawLevel = parseInt(heading.tagName.slice(1), 10);
        if (isNaN(rawLevel)) return 1;
        var level = rawLevel - headingOffset;
        if (level < 1) level = 1;
        if (level > 6) level = 6;
        return level;
      }
      
      // Filter headings to only include those within requested depth, PRESERVING document order
      var tocHeadings = allHeadings.filter(function(h) {
        var level = getEffectiveLevel(h);
        return level <= tocDepth;
      });
      
      // Detect if manual uses "Section" or "Chapter"
      // Read from data attribute first
      var manualTypeAttr = grid.getAttribute("data-manual-type");
      var usesSections = (manualTypeAttr === "section");

      // ALWAYS check first H1 content to verify or override
      // This ensures "Section" manuals are detected even if attribute is missing or wrong
      var firstH1 = manual.querySelector("h1");
      if (firstH1) {
        var firstH1Text = (firstH1.textContent || firstH1.innerText || "").trim();
        // Check for Section style headings (Section I, Section 1, etc.)
        if (/^Section\s+/i.test(firstH1Text)) {
           usesSections = true;
        }
      }

      var chapterLabel = usesSections ? "Section" : "Chapter";

      // Check numbering mode - if "preserve", headings already have numbers in text
      // Use getAttribute to be safe against dataset quirks
      var numberingMode = grid.getAttribute("data-numbering-mode") || "css-counters";
      var addTocPrefix = (numberingMode === "css-counters");

      var slug = function (s) {
        return String(s || "")
          .toLowerCase()
          .replace(/chapter\s+\w+\s*[–—-]\s*/i, "")  // strip "Chapter X – "
          .replace(/[^\w\s.-]/g, "")
          .trim()
          .replace(/\s+/g, "-")
          .replace(/-+/g, "-")
          .replace(/^-+|-+$/g, ""); // Remove leading/trailing dashes
      };

      // Helper function to find nearest parent heading
      var findNearestHeading = function(element) {
        var current = element;
        while (current && current !== manual) {
          current = current.previousElementSibling || current.parentElement;
          if (current && current.matches && current.matches("h1, h2, h3, h4, h5, h6")) {
            return current;
          }
        }
        return null;
      };

      // Process ALL headings for IDs and copy-link functionality
      var allHeadingsData = [];
      for (var i = 0; i < allHeadings.length; i++) {
        var h = allHeadings[i];
        var title = (h.textContent || h.innerText || "").trim();
        var cleanTitle = title.replace(/^\d+(\.\d+)*\s*/, ""); // Remove number prefixes for search
        h.dataset.title = title;
        h.dataset.searchTitle = cleanTitle;
        if (!h.id) h.id = slug(cleanTitle) || ("heading-" + i);

        // Store heading data for search
        allHeadingsData.push({
          id: h.id,
          title: title,
          searchTitle: cleanTitle,
          level: getEffectiveLevel(h),
          element: h
        });

        if (getEffectiveLevel(h) === 1) {
          continue;
        }

        if (!h.querySelector(".heading-link-icon")) {
          var icon = document.createElement("button");
          icon.type = "button";
          icon.className = "heading-link-icon";
          icon.textContent = "🔗";
          icon.setAttribute("aria-label", "Copy link to this section");
          icon.title = "Copy link";
          icon.addEventListener("click", function (evt) {
            evt.stopPropagation();
            var host = location.origin || (location.protocol + "//" + location.host);
            var url = host + location.pathname + "#" + this.parentElement.id;
            // Fallback for older browsers
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(url).then(function() {
                var iconElem = evt.target;
                iconElem.textContent = "✓";
                setTimeout(function() { iconElem.textContent = "🔗"; }, 1000);
              }).catch(function() {
                fallbackCopy(url);
              });
            } else {
              fallbackCopy(url);
            }

            function fallbackCopy(text) {
              var tmp = document.createElement("input");
              tmp.value = text;
              document.body.appendChild(tmp);
              tmp.select();
              try { document.execCommand("copy"); } catch (e) {}
              document.body.removeChild(tmp);
            }
          });
          h.appendChild(icon);
        }
      }

      /* ----- Index page content for search ----- */
      var contentData = [];
      var contentElements = manual.querySelectorAll('p, li, td, blockquote, dt, dd');
      for (var c = 0; c < contentElements.length; c++) {
        var element = contentElements[c];
        var text = (element.textContent || element.innerText || "").trim();
        if (text.length > 10) { // Only index substantial content
          var nearestHeading = findNearestHeading(element);
          contentData.push({
            text: text,
            element: element,
            parentHeading: nearestHeading,
            parentHeadingTitle: nearestHeading ? (nearestHeading.dataset.title || nearestHeading.textContent) : "Introduction"
          });
        }
      }

      /* ----- Build Collapsible TOC (H1 with expandable H2s) ----- */
      tocList.innerHTML = "";
      var chapterNumber = 0;
      
      // Map to store chapter LI elements by their H1 element
      var chapterMap = new Map(); // Maps H1 element -> {li: chapterLi, subList: subList}
      
      // First pass: Create all H1 entries
      for (var j = 0; j < tocHeadings.length; j++) {
        var hh = tocHeadings[j];
        var level = getEffectiveLevel(hh);
        
        if (level === 1) {
          chapterNumber++;
          var linkText = hh.dataset.title || (hh.textContent || hh.innerText).trim();
          
          var chapterLi = document.createElement("li");
          chapterLi.setAttribute("data-level", "1");
          chapterLi.className = "toc-chapter";

          // Create the chapter link container
          var chapterContainer = document.createElement("div");
          chapterContainer.className = "toc-chapter-header";

          // Create expand/collapse button
          var expandBtn = document.createElement("button");
          expandBtn.className = "toc-expand-btn";
          expandBtn.innerHTML = "▶";
          expandBtn.setAttribute("aria-expanded", "false");
          // Create unique ID for subsections list for aria-controls
          var subsectionId = "toc-subsections-" + chapterNumber;
          expandBtn.setAttribute("aria-controls", subsectionId);
          expandBtn.setAttribute("aria-label", "Expand " + linkText);
          expandBtn.style.cssText = [
            "background: none",
            "border: none",
            "cursor: pointer",
            "padding: 2px 6px",
            "margin-right: 6px",
            "font-size: 12px",
            "color: #666",
            "transition: transform 0.3s ease"
          ].join("; ");

          // Create the chapter/section link
          var chapterLink = document.createElement("a");
          chapterLink.href = "#" + hh.id;
          
          // Safety check: If linkText already starts with Chapter/Section/Table of Contents, or looks like a TOC entry, don't add prefix
          var effectiveAddPrefix = addTocPrefix;
          var linkTextClean = linkText.trim();
          
          // Fail-safe: If text starts with the label (e.g. "Section I" starts with "Section"), don't add prefix
          if (linkTextClean.toLowerCase().indexOf(chapterLabel.toLowerCase()) === 0) {
             effectiveAddPrefix = false;
          }
          
          // Enhanced regex to catch "Section I", "Section: I", "SectionI", etc.
          if (/^(Chapter|Section)(?:\s|[.:-]|$)/i.test(linkTextClean) || /^\d+\.?\s/.test(linkTextClean) || /^[IVXLCDM]+\.?\s/.test(linkTextClean)) {
             effectiveAddPrefix = false;
          }

          // Only add prefix if using CSS counters; if preserving, numbers already in text
          chapterLink.textContent = effectiveAddPrefix ? (chapterLabel + " " + chapterNumber + ". " + linkText) : linkText;
          chapterLink.style.textDecoration = "none";

          chapterContainer.appendChild(expandBtn);
          chapterContainer.appendChild(chapterLink);
          chapterLi.appendChild(chapterContainer);

          // Create sub-list for H2+ entries (initially hidden)
          var subList = document.createElement("ul");
          subList.id = subsectionId; // Set ID for aria-controls
          subList.className = "toc-subsections toc-collapsed";
          subList.setAttribute("role", "region");
          subList.setAttribute("aria-label", "Subsections of " + linkText);
          subList.style.cssText = [
            "margin: 4px 0 0 20px",
            "padding: 0",
            "list-style: none"
          ].join("; ");
          chapterLi.appendChild(subList);

          tocList.appendChild(chapterLi);

          // Store mapping: H1 element -> chapter data
          chapterMap.set(hh, { li: chapterLi, subList: subList });

          // Add click handler for expand/collapse
          expandBtn.addEventListener("click", function(e) {
            e.preventDefault();
            e.stopPropagation();

            var isExpanded = this.getAttribute("aria-expanded") === "true";
            var subSections = this.parentElement.parentElement.querySelector(".toc-subsections");

            if (isExpanded) {
              this.setAttribute("aria-expanded", "false");
              subSections.classList.remove("toc-expanded");
              subSections.classList.add("toc-collapsed");
            } else {
              this.setAttribute("aria-expanded", "true");
              subSections.classList.remove("toc-collapsed");
              subSections.classList.add("toc-expanded");
            }
          });
        }
      }

      // Second pass: Add H2+ headings to their parent H1's sublist
      // Find the correct parent H1 by walking backwards in the DOM
      for (var j = 0; j < tocHeadings.length; j++) {
        var hh = tocHeadings[j];
        var level = getEffectiveLevel(hh);
        
        if (level >= 2 && level <= tocDepth) {
          // Find the parent H1 by walking backwards through previous siblings
          var parentH1 = null;
          var current = hh.previousElementSibling;
          
          while (current) {
            if (current.matches && current.matches("h1, h2, h3, h4, h5, h6") && getEffectiveLevel(current) === 1) {
              parentH1 = current;
              break;
            }
            current = current.previousElementSibling;
          }
          
          // If not found in previous siblings, check parent elements
          if (!parentH1) {
            current = hh.parentElement;
            while (current && current !== manual) {
              var parentHeadings = current.querySelectorAll('h1, h2, h3, h4, h5, h6');
              for (var p = 0; p < parentHeadings.length; p++) {
                var candidate = parentHeadings[p];
                if (manual.contains(candidate) && getEffectiveLevel(candidate) === 1) {
                  var allElements = Array.prototype.slice.call(manual.querySelectorAll('h1, h2, h3, h4, h5, h6'));
                  var parentIndex = allElements.indexOf(candidate);
                  var headingIndex = allElements.indexOf(hh);
                  if (parentIndex > -1 && headingIndex > -1 && parentIndex < headingIndex) {
                    parentH1 = candidate;
                    break;
                  }
                }
              }
              if (parentH1) {
                break;
              }
              current = current.parentElement;
            }
          }
          
          // Fallback: find the last H1 that appears before this heading in the headings array
          if (!parentH1) {
            for (var k = j - 1; k >= 0; k--) {
              if (getEffectiveLevel(tocHeadings[k]) === 1) {
                parentH1 = tocHeadings[k];
                break;
              }
            }
          }
          
          // Add to parent H1's sublist if found
          if (parentH1 && chapterMap.has(parentH1)) {
            var chapterData = chapterMap.get(parentH1);
            var linkText = hh.dataset.title || (hh.textContent || hh.innerText).trim();
            
            var sectionLi = document.createElement("li");
            sectionLi.setAttribute("data-level", level.toString());
            sectionLi.className = "toc-section";

            var sectionLink = document.createElement("a");
            sectionLink.href = "#" + hh.id;
            sectionLink.textContent = linkText;
            // Remove inline font-weight - let CSS handle it with !important
            // Only set layout properties inline, styling comes from CSS
            sectionLink.style.cssText = [
              "display: block",
              "padding: 2px 6px",
              "text-decoration: none",
              "border-radius: 3px",
              "font-size: " + (level > 2 ? "12px" : "13px"),
              "margin-left: " + ((level - 2) * 20) + "px"
            ].join("; ");
            // Explicitly set font-weight using setProperty with !important
            sectionLink.style.setProperty('font-weight', '400', 'important');
            sectionLink.style.setProperty('color', '#666', 'important');

            sectionLi.appendChild(sectionLink);
            chapterData.subList.appendChild(sectionLi);

            // Show the expand button for the parent chapter
            var expandBtn = chapterData.li.querySelector(".toc-expand-btn");
            if (expandBtn) {
              expandBtn.style.visibility = "visible";
            }
          }
        }
      }

      // Hide expand buttons for chapters with no subsections
      var allExpandBtns = tocList.querySelectorAll(".toc-expand-btn");
      allExpandBtns.forEach(function(btn) {
        var subList = btn.parentElement.parentElement.querySelector(".toc-subsections");
        if (!subList || subList.children.length === 0) {
          btn.style.visibility = "hidden";
        }
      });

        /* ----- Enhanced Search Box - searches headings AND content ----- */
        if (tocSearch) {
          // Update placeholder text
          tocSearch.placeholder = "Search headings and content...";
          
          // Create aria-live region for screen reader announcements
          var searchStatus = document.createElement("div");
          searchStatus.className = "manual-search-status sr-only";
          searchStatus.setAttribute("aria-live", "polite");
          searchStatus.style.cssText = "position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;";
          toc.insertBefore(searchStatus, tocList);

          var searchResults = document.createElement("div");
          searchResults.className = "manual-search-results";
          searchResults.setAttribute("aria-label", "Search results");
          searchResults.style.display = "none";
          searchResults.style.marginTop = "8px";
          searchResults.style.minHeight = "0";
          searchResults.style.maxHeight = "400px";
          searchResults.style.overflowY = "auto";
          searchResults.style.border = "1px solid #ddd";
          searchResults.style.borderRadius = "4px";
          searchResults.style.background = "#fff";
          searchResults.style.boxShadow = "0 2px 8px rgba(0,0,0,0.1)";
          toc.insertBefore(searchResults, tocList);

          var createSnippet = function(text, query, maxLength) {
            if (!text || !query) return "";
            maxLength = maxLength || 120;

            var lowerText = text.toLowerCase();
            var lowerQuery = query.toLowerCase();
            var index = lowerText.indexOf(lowerQuery);

            if (index === -1) return text.substring(0, maxLength) + "...";

            var start = Math.max(0, index - 40);
            var end = Math.min(text.length, index + query.length + 40);

            var snippet = (start > 0 ? "..." : "") +
              text.substring(start, end) +
              (end < text.length ? "..." : "");

            // Highlight the matched term
            var regex = new RegExp("(" + query.replace(/[.*+?^${}()|[\\]/g, '\\$&') + ")", 'gi');
            snippet = snippet.replace(regex, '<span class=\"manual-search-highlight\">$1</span>');

            return snippet;
          };

          if (tocSearch && tocSearch.getAttribute("type") === "search") {
            var replacement = tocSearch.cloneNode(true);
            replacement.setAttribute("type", "text");
            replacement.setAttribute("role", "searchbox");
            replacement.classList.add("manual-search-input");
            tocSearch.parentElement.replaceChild(replacement, tocSearch);
            tocSearch = replacement;
          }

          if (tocSearch && (!tocClear)) {
            var wrap = tocSearch.parentElement;
            // Check if we need to create the wrapper
            if (!wrap || !wrap.classList.contains("manual-search")) {
              var newWrap = document.createElement("div");
              newWrap.className = "manual-search";
              // Capture the original parent before moving elements
              var originalParent = tocSearch.parentElement;
              if (originalParent) {
                originalParent.insertBefore(newWrap, tocSearch);
                newWrap.appendChild(tocSearch);
                // Update wrap to point to our new wrapper
                wrap = newWrap;
              }
            }
            
            tocClear = document.createElement("button");
            tocClear.type = "button";
            tocClear.className = "manual-search-clear";
            tocClear.setAttribute("aria-label", "Clear search");
            tocClear.textContent = "X";
            
            // Append to the correct wrapper (either existing or newly created)
            if (wrap) {
              wrap.appendChild(tocClear);
            }
          }

          var searchWrap = null;
          if (tocSearch) {
            if (tocSearch.parentElement && tocSearch.parentElement.classList.contains("manual-search")) {
              searchWrap = tocSearch.parentElement;
            } else if (tocSearch.closest) {
              searchWrap = tocSearch.closest(".manual-search");
            }
          }

          function setClearVisibility(show) {
            if (searchWrap) {
              if (show) {
                searchWrap.classList.add("has-value");
              } else {
                searchWrap.classList.remove("has-value");
              }
            }
            if (tocClear) {
              tocClear.style.display = show ? "" : "none";
            }
          }

          if (tocClear) {
            tocClear.addEventListener("click", function() {
              clearSearch();
              tocSearch.focus();
            });
          }
          setClearVisibility(!!(tocSearch && tocSearch.value && tocSearch.value.trim()));

          var lastSearchTarget = null;
          var lastSearchResult = null;

          function setSearchTarget(element) {
            if (lastSearchTarget) {
              lastSearchTarget.classList.remove("manual-search-target");
            }
            lastSearchTarget = element || null;
            if (lastSearchTarget) {
              lastSearchTarget.classList.add("manual-search-target");
              if (lastSearchTarget.tabIndex < 0) lastSearchTarget.setAttribute("tabindex", "-1");
              lastSearchTarget.focus({preventScroll: true});
            }
          }

          function setSearchResultActive(button) {
            if (lastSearchResult) {
              lastSearchResult.classList.remove("manual-search-result-active");
              lastSearchResult.removeAttribute("aria-current");
            }
            lastSearchResult = button || null;
            if (lastSearchResult) {
              lastSearchResult.classList.add("manual-search-result-active");
              lastSearchResult.setAttribute("aria-current", "true");
            }
          }

          function clearSearch() {
            tocSearch.value = "";
            tocList.style.display = "";
            searchResults.style.display = "none";
            searchResults.innerHTML = "";
            searchStatus.textContent = "";
            setSearchTarget(null);
            setSearchResultActive(null);
            setClearVisibility(false);
          }

          function navigateToElement(id) {
            var targetElement = document.getElementById(id);
            if (targetElement) {
              targetElement.scrollIntoView({
                behavior: prefersReducedMotion ? "auto" : "smooth",
                block: "start"
              });
              activate(id);
            }
          }

          tocSearch.addEventListener("input", function () {
            var q = this.value.toLowerCase().trim();

            if (!q) {
              // Show normal TOC, hide search results
              tocList.style.display = "";
              searchResults.style.display = "none";
              searchResults.innerHTML = "";
              searchStatus.textContent = "";
              setSearchTarget(null);
              setSearchResultActive(null);
              setClearVisibility(false);
              return;
            }
            setSearchResultActive(null);
            setClearVisibility(true);

            // Hide normal TOC and show search results
            tocList.style.display = "none";
            searchResults.style.display = "block";
            searchResults.innerHTML = "";

            // Search through headings
            var headingMatches = [];
            for (var k = 0; k < allHeadingsData.length; k++) {
              var heading = allHeadingsData[k];
              if (heading.searchTitle.toLowerCase().indexOf(q) !== -1) {
                headingMatches.push(heading);
              }
            }

            // Search through content
            var contentMatches = [];
            for (var l = 0; l < contentData.length; l++) {
              var content = contentData[l];
              if (content.text.toLowerCase().indexOf(q) !== -1) {
                contentMatches.push(content);
              }
            }

            if (headingMatches.length === 0 && contentMatches.length === 0) {
              searchResults.innerHTML = "<div style='padding: 12px; color: #666; font-style: italic; text-align: center;'>No matches found</div>";
              searchStatus.textContent = "No matches found";
              return;
            }
            
            // Update screen reader status
            searchStatus.textContent = "Found " + headingMatches.length + " headings and " + contentMatches.length + " content matches.";

            var resultsHTML = "";

            // Display heading matches
            if (headingMatches.length > 0) {
              var headingHeader = document.createElement("div");
              headingHeader.style.cssText = "padding: 8px 12px 4px; background: #f8f9fa; border-bottom: 1px solid #e9ecef; font-weight: 600; color: #495057; font-size: 13px;";
              headingHeader.textContent = "📍 HEADINGS (" + headingMatches.length + " match" + (headingMatches.length !== 1 ? "es" : "") + ")";
              searchResults.appendChild(headingHeader);

              for (var m = 0; m < Math.min(headingMatches.length, 8); m++) { // Limit to 8 heading results
                var match = headingMatches[m];
                // Use button for accessibility (keyboard focusable + click/enter support)
                var resultItem = document.createElement("button");
                resultItem.type = "button";
                resultItem.setAttribute("tabindex", "0");
                resultItem.classList.add("manual-search-result");
                resultItem.style.cssText = "display: block; width: 100%; text-align: left; background: none; border: none; padding: 8px 12px; border-bottom: 1px solid #eee; cursor: pointer; font-family: inherit;";

                var levelIndicator = "";
                for (var lvl = 1; lvl < match.level; lvl++) {
                  levelIndicator += "  ";
                }

                resultItem.innerHTML = levelIndicator + match.title;
                resultItem.style.fontSize = match.level > 2 ? "0.9em" : "1em";
                resultItem.style.color = match.level > 2 ? "#666" : "#000";

                resultItem.addEventListener("click", (function(headingId) {
                  return function() {
                    var target = document.getElementById(headingId);
                    setSearchResultActive(this);
                    if (target) setSearchTarget(target);
                    navigateToElement(headingId);
                  };
                })(match.id));
                searchResults.appendChild(resultItem);
              }
            }

            // Display content matches
            if (contentMatches.length > 0) {
              var contentHeader = document.createElement("div");
              contentHeader.style.cssText = "padding: 8px 12px 4px; background: #f8f9fa; border-bottom: 1px solid #e9ecef; font-weight: 600; color: #495057; font-size: 13px;";
              contentHeader.textContent = "📄 CONTENT (" + contentMatches.length + " match" + (contentMatches.length !== 1 ? "es" : "") + ")";
              searchResults.appendChild(contentHeader);

              for (var n = 0; n < Math.min(contentMatches.length, 10); n++) { // Limit to 10 content results
                var contentMatch = contentMatches[n];
                // Use button for accessibility
                var contentItem = document.createElement("button");
                contentItem.type = "button";
                contentItem.classList.add("manual-search-result");
                contentItem.style.cssText = "display: block; width: 100%; text-align: left; background: none; border: none; padding: 8px 12px; border-bottom: 1px solid #eee; cursor: pointer; font-family: inherit; font-size: 0.9em;";

                var snippet = createSnippet(contentMatch.text, q);
                var parentInfo = contentMatch.parentHeadingTitle ?
                  " <span style='color: #666; font-size: 0.85em;'>(in " + contentMatch.parentHeadingTitle + ")</span>" : "";

                contentItem.innerHTML = snippet + parentInfo;

                contentItem.addEventListener("click", (function(element) {
                  return function() {
                    element.scrollIntoView({ behavior: "smooth", block: "center" });
                    setSearchResultActive(this);
                    setSearchTarget(element);
                  };
                })(contentMatch.element));
                searchResults.appendChild(contentItem);
              }
            }
          });
      }

      /* ----- Scrollspy (.active + aria-current) for TOC headings only ----- */
      var linksById = {};
      var tocLinks = tocList.querySelectorAll("a");
      for (var n = 0; n < tocLinks.length; n++) {
        var a3 = tocLinks[n];
        linksById[a3.getAttribute("href").slice(1)] = a3;
      }

      var activate = function (id) {
        var actives = tocList.querySelectorAll("a.active");
        for (var x = 0; x < actives.length; x++) actives[x].classList.remove("active");
        var currents = tocList.querySelectorAll("a[aria-current='true']");
        for (var y = 0; y < currents.length; y++) currents[y].removeAttribute("aria-current");
        var link = linksById[id];
        if (link) {
          link.classList.add("active");
          link.setAttribute("aria-current", "true");
        }
      };

      // Intersection Observer for TOC headings only (H1-H2)
      if ("IntersectionObserver" in window) {
        var io = new IntersectionObserver(function (entries) {
          for (var z = 0; z < entries.length; z++) {
            if (entries[z].isIntersecting) activate(entries[z].target.id);
          }
        }, { rootMargin: "0px 0px -70% 0px", threshold: 0.1 });
        for (var p = 0; p < tocHeadings.length; p++) io.observe(tocHeadings[p]);
      }

      if (location.hash && linksById[location.hash.slice(1)]) {
        activate(location.hash.slice(1));
      }

      // Set smooth scrolling with better WordPress compatibility and reduced motion support
      if (document.documentElement.style.scrollBehavior !== undefined && !prefersReducedMotion) {
        document.documentElement.style.scrollBehavior = "smooth";
      }

      /* ----- Back-to-top (always present, hover to brighten) ----- */
      if (!document.getElementById("manual-back-to-top")) {
        var btn = document.createElement("button");
        btn.id = "manual-back-to-top";
        btn.type = "button";
        btn.setAttribute("aria-label", "Back to top");
        btn.textContent = "↑ Top";
        btn.addEventListener("click", function () {
          if (window.scrollTo) {
            window.scrollTo({
              top: 0,
              behavior: prefersReducedMotion ? "auto" : "smooth"
            });
          } else {
            // Fallback for older browsers
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
          }
        });
        document.body.appendChild(btn);
      }

      /* External links inside content open in a new tab (don't touch internal anchors) */
      var externals = manual.querySelectorAll('a[href^="http"]');
      for (var e = 0; e < externals.length; e++) {
        try {
          var currentHref = externals[e].href;
          var currentOrigin = location.origin || (location.protocol + "//" + location.host);

          // Simple check for external links
          if (currentHref.indexOf(currentOrigin) !== 0) {
            externals[e].target = "_blank";
            externals[e].rel = "noopener";
          }
        } catch (_err) {
          // Ignore URL parsing errors
        }
      }
    }
  }

  // Enhanced initialization for WordPress compatibility
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initManual);
  } else if (document.readyState === 'interactive' || document.readyState === 'complete') {
    // Document is already loaded
    initManual();
  }

  // Additional fallback for WordPress themes that may load content dynamically
  setTimeout(function() {
    var grids = document.querySelectorAll(".manual-grid:not([data-gspp-enhanced='1'])");
    if (grids.length) {
      processManualGrids(grids);
    }
  }, 500);

})();