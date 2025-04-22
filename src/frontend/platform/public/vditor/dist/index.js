/*!
 * Vditor v3.10.5 - A markdown editor written in TypeScript.
 *
 * MIT License
 *
 * Copyright (c) 2018-present B3log 开源, b3log.org
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 *
 */
(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory();
	else if(typeof define === 'function' && define.amd)
		define([], factory);
	else if(typeof exports === 'object')
		exports["Vditor"] = factory();
	else
		root["Vditor"] = factory();
})(this, () => {
return /******/ (() => { // webpackBootstrap
/******/ 	var __webpack_modules__ = ({

/***/ 85:
/***/ ((module) => {

/**
 * Diff Match and Patch
 * Copyright 2018 The diff-match-patch Authors.
 * https://github.com/google/diff-match-patch
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * @fileoverview Computes the difference between two texts to create a patch.
 * Applies the patch onto another text, allowing for errors.
 * @author fraser@google.com (Neil Fraser)
 */

/**
 * Class containing the diff, match and patch methods.
 * @constructor
 */
var diff_match_patch = function () {
  // Defaults.
  // Redefine these in your program to override the defaults.

  // Number of seconds to map a diff before giving up (0 for infinity).
  this.Diff_Timeout = 1.0;
  // Cost of an empty edit operation in terms of edit characters.
  this.Diff_EditCost = 4;
  // At what point is no match declared (0.0 = perfection, 1.0 = very loose).
  this.Match_Threshold = 0.5;
  // How far to search for a match (0 = exact location, 1000+ = broad match).
  // A match this many characters away from the expected location will add
  // 1.0 to the score (0.0 is a perfect match).
  this.Match_Distance = 1000;
  // When deleting a large block of text (over ~64 characters), how close do
  // the contents have to be to match the expected contents. (0.0 = perfection,
  // 1.0 = very loose).  Note that Match_Threshold controls how closely the
  // end points of a delete need to match.
  this.Patch_DeleteThreshold = 0.5;
  // Chunk size for context length.
  this.Patch_Margin = 4;

  // The number of bits in an int.
  this.Match_MaxBits = 32;
};

//  DIFF FUNCTIONS

/**
 * The data structure representing a diff is an array of tuples:
 * [[DIFF_DELETE, 'Hello'], [DIFF_INSERT, 'Goodbye'], [DIFF_EQUAL, ' world.']]
 * which means: delete 'Hello', add 'Goodbye' and keep ' world.'
 */
var DIFF_DELETE = -1;
var DIFF_INSERT = 1;
var DIFF_EQUAL = 0;

/**
 * Class representing one diff tuple.
 * ~Attempts to look like a two-element array (which is what this used to be).~
 * Constructor returns an actual two-element array, to allow destructing @JackuB
 * See https://github.com/JackuB/diff-match-patch/issues/14 for details
 * @param {number} op Operation, one of: DIFF_DELETE, DIFF_INSERT, DIFF_EQUAL.
 * @param {string} text Text to be deleted, inserted, or retained.
 * @constructor
 */
diff_match_patch.Diff = function (op, text) {
  return [op, text];
};

/**
 * Find the differences between two texts.  Simplifies the problem by stripping
 * any common prefix or suffix off the texts before diffing.
 * @param {string} text1 Old string to be diffed.
 * @param {string} text2 New string to be diffed.
 * @param {boolean=} opt_checklines Optional speedup flag. If present and false,
 *     then don't run a line-level diff first to identify the changed areas.
 *     Defaults to true, which does a faster, slightly less optimal diff.
 * @param {number=} opt_deadline Optional time when the diff should be complete
 *     by.  Used internally for recursive calls.  Users should set DiffTimeout
 *     instead.
 * @return {!Array.<!diff_match_patch.Diff>} Array of diff tuples.
 */
diff_match_patch.prototype.diff_main = function (text1, text2, opt_checklines, opt_deadline) {
  // Set a deadline by which time the diff must be complete.
  if (typeof opt_deadline == 'undefined') {
    if (this.Diff_Timeout <= 0) {
      opt_deadline = Number.MAX_VALUE;
    } else {
      opt_deadline = new Date().getTime() + this.Diff_Timeout * 1000;
    }
  }
  var deadline = opt_deadline;

  // Check for null inputs.
  if (text1 == null || text2 == null) {
    throw new Error('Null input. (diff_main)');
  }

  // Check for equality (speedup).
  if (text1 == text2) {
    if (text1) {
      return [new diff_match_patch.Diff(DIFF_EQUAL, text1)];
    }
    return [];
  }
  if (typeof opt_checklines == 'undefined') {
    opt_checklines = true;
  }
  var checklines = opt_checklines;

  // Trim off common prefix (speedup).
  var commonlength = this.diff_commonPrefix(text1, text2);
  var commonprefix = text1.substring(0, commonlength);
  text1 = text1.substring(commonlength);
  text2 = text2.substring(commonlength);

  // Trim off common suffix (speedup).
  commonlength = this.diff_commonSuffix(text1, text2);
  var commonsuffix = text1.substring(text1.length - commonlength);
  text1 = text1.substring(0, text1.length - commonlength);
  text2 = text2.substring(0, text2.length - commonlength);

  // Compute the diff on the middle block.
  var diffs = this.diff_compute_(text1, text2, checklines, deadline);

  // Restore the prefix and suffix.
  if (commonprefix) {
    diffs.unshift(new diff_match_patch.Diff(DIFF_EQUAL, commonprefix));
  }
  if (commonsuffix) {
    diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, commonsuffix));
  }
  this.diff_cleanupMerge(diffs);
  return diffs;
};

/**
 * Find the differences between two texts.  Assumes that the texts do not
 * have any common prefix or suffix.
 * @param {string} text1 Old string to be diffed.
 * @param {string} text2 New string to be diffed.
 * @param {boolean} checklines Speedup flag.  If false, then don't run a
 *     line-level diff first to identify the changed areas.
 *     If true, then run a faster, slightly less optimal diff.
 * @param {number} deadline Time when the diff should be complete by.
 * @return {!Array.<!diff_match_patch.Diff>} Array of diff tuples.
 * @private
 */
diff_match_patch.prototype.diff_compute_ = function (text1, text2, checklines, deadline) {
  var diffs;
  if (!text1) {
    // Just add some text (speedup).
    return [new diff_match_patch.Diff(DIFF_INSERT, text2)];
  }
  if (!text2) {
    // Just delete some text (speedup).
    return [new diff_match_patch.Diff(DIFF_DELETE, text1)];
  }
  var longtext = text1.length > text2.length ? text1 : text2;
  var shorttext = text1.length > text2.length ? text2 : text1;
  var i = longtext.indexOf(shorttext);
  if (i != -1) {
    // Shorter text is inside the longer text (speedup).
    diffs = [new diff_match_patch.Diff(DIFF_INSERT, longtext.substring(0, i)), new diff_match_patch.Diff(DIFF_EQUAL, shorttext), new diff_match_patch.Diff(DIFF_INSERT, longtext.substring(i + shorttext.length))];
    // Swap insertions for deletions if diff is reversed.
    if (text1.length > text2.length) {
      diffs[0][0] = diffs[2][0] = DIFF_DELETE;
    }
    return diffs;
  }
  if (shorttext.length == 1) {
    // Single character string.
    // After the previous speedup, the character can't be an equality.
    return [new diff_match_patch.Diff(DIFF_DELETE, text1), new diff_match_patch.Diff(DIFF_INSERT, text2)];
  }

  // Check to see if the problem can be split in two.
  var hm = this.diff_halfMatch_(text1, text2);
  if (hm) {
    // A half-match was found, sort out the return data.
    var text1_a = hm[0];
    var text1_b = hm[1];
    var text2_a = hm[2];
    var text2_b = hm[3];
    var mid_common = hm[4];
    // Send both pairs off for separate processing.
    var diffs_a = this.diff_main(text1_a, text2_a, checklines, deadline);
    var diffs_b = this.diff_main(text1_b, text2_b, checklines, deadline);
    // Merge the results.
    return diffs_a.concat([new diff_match_patch.Diff(DIFF_EQUAL, mid_common)], diffs_b);
  }
  if (checklines && text1.length > 100 && text2.length > 100) {
    return this.diff_lineMode_(text1, text2, deadline);
  }
  return this.diff_bisect_(text1, text2, deadline);
};

/**
 * Do a quick line-level diff on both strings, then rediff the parts for
 * greater accuracy.
 * This speedup can produce non-minimal diffs.
 * @param {string} text1 Old string to be diffed.
 * @param {string} text2 New string to be diffed.
 * @param {number} deadline Time when the diff should be complete by.
 * @return {!Array.<!diff_match_patch.Diff>} Array of diff tuples.
 * @private
 */
diff_match_patch.prototype.diff_lineMode_ = function (text1, text2, deadline) {
  // Scan the text on a line-by-line basis first.
  var a = this.diff_linesToChars_(text1, text2);
  text1 = a.chars1;
  text2 = a.chars2;
  var linearray = a.lineArray;
  var diffs = this.diff_main(text1, text2, false, deadline);

  // Convert the diff back to original text.
  this.diff_charsToLines_(diffs, linearray);
  // Eliminate freak matches (e.g. blank lines)
  this.diff_cleanupSemantic(diffs);

  // Rediff any replacement blocks, this time character-by-character.
  // Add a dummy entry at the end.
  diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, ''));
  var pointer = 0;
  var count_delete = 0;
  var count_insert = 0;
  var text_delete = '';
  var text_insert = '';
  while (pointer < diffs.length) {
    switch (diffs[pointer][0]) {
      case DIFF_INSERT:
        count_insert++;
        text_insert += diffs[pointer][1];
        break;
      case DIFF_DELETE:
        count_delete++;
        text_delete += diffs[pointer][1];
        break;
      case DIFF_EQUAL:
        // Upon reaching an equality, check for prior redundancies.
        if (count_delete >= 1 && count_insert >= 1) {
          // Delete the offending records and add the merged ones.
          diffs.splice(pointer - count_delete - count_insert, count_delete + count_insert);
          pointer = pointer - count_delete - count_insert;
          var subDiff = this.diff_main(text_delete, text_insert, false, deadline);
          for (var j = subDiff.length - 1; j >= 0; j--) {
            diffs.splice(pointer, 0, subDiff[j]);
          }
          pointer = pointer + subDiff.length;
        }
        count_insert = 0;
        count_delete = 0;
        text_delete = '';
        text_insert = '';
        break;
    }
    pointer++;
  }
  diffs.pop(); // Remove the dummy entry at the end.

  return diffs;
};

/**
 * Find the 'middle snake' of a diff, split the problem in two
 * and return the recursively constructed diff.
 * See Myers 1986 paper: An O(ND) Difference Algorithm and Its Variations.
 * @param {string} text1 Old string to be diffed.
 * @param {string} text2 New string to be diffed.
 * @param {number} deadline Time at which to bail if not yet complete.
 * @return {!Array.<!diff_match_patch.Diff>} Array of diff tuples.
 * @private
 */
diff_match_patch.prototype.diff_bisect_ = function (text1, text2, deadline) {
  // Cache the text lengths to prevent multiple calls.
  var text1_length = text1.length;
  var text2_length = text2.length;
  var max_d = Math.ceil((text1_length + text2_length) / 2);
  var v_offset = max_d;
  var v_length = 2 * max_d;
  var v1 = new Array(v_length);
  var v2 = new Array(v_length);
  // Setting all elements to -1 is faster in Chrome & Firefox than mixing
  // integers and undefined.
  for (var x = 0; x < v_length; x++) {
    v1[x] = -1;
    v2[x] = -1;
  }
  v1[v_offset + 1] = 0;
  v2[v_offset + 1] = 0;
  var delta = text1_length - text2_length;
  // If the total number of characters is odd, then the front path will collide
  // with the reverse path.
  var front = delta % 2 != 0;
  // Offsets for start and end of k loop.
  // Prevents mapping of space beyond the grid.
  var k1start = 0;
  var k1end = 0;
  var k2start = 0;
  var k2end = 0;
  for (var d = 0; d < max_d; d++) {
    // Bail out if deadline is reached.
    if (new Date().getTime() > deadline) {
      break;
    }

    // Walk the front path one step.
    for (var k1 = -d + k1start; k1 <= d - k1end; k1 += 2) {
      var k1_offset = v_offset + k1;
      var x1;
      if (k1 == -d || k1 != d && v1[k1_offset - 1] < v1[k1_offset + 1]) {
        x1 = v1[k1_offset + 1];
      } else {
        x1 = v1[k1_offset - 1] + 1;
      }
      var y1 = x1 - k1;
      while (x1 < text1_length && y1 < text2_length && text1.charAt(x1) == text2.charAt(y1)) {
        x1++;
        y1++;
      }
      v1[k1_offset] = x1;
      if (x1 > text1_length) {
        // Ran off the right of the graph.
        k1end += 2;
      } else if (y1 > text2_length) {
        // Ran off the bottom of the graph.
        k1start += 2;
      } else if (front) {
        var k2_offset = v_offset + delta - k1;
        if (k2_offset >= 0 && k2_offset < v_length && v2[k2_offset] != -1) {
          // Mirror x2 onto top-left coordinate system.
          var x2 = text1_length - v2[k2_offset];
          if (x1 >= x2) {
            // Overlap detected.
            return this.diff_bisectSplit_(text1, text2, x1, y1, deadline);
          }
        }
      }
    }

    // Walk the reverse path one step.
    for (var k2 = -d + k2start; k2 <= d - k2end; k2 += 2) {
      var k2_offset = v_offset + k2;
      var x2;
      if (k2 == -d || k2 != d && v2[k2_offset - 1] < v2[k2_offset + 1]) {
        x2 = v2[k2_offset + 1];
      } else {
        x2 = v2[k2_offset - 1] + 1;
      }
      var y2 = x2 - k2;
      while (x2 < text1_length && y2 < text2_length && text1.charAt(text1_length - x2 - 1) == text2.charAt(text2_length - y2 - 1)) {
        x2++;
        y2++;
      }
      v2[k2_offset] = x2;
      if (x2 > text1_length) {
        // Ran off the left of the graph.
        k2end += 2;
      } else if (y2 > text2_length) {
        // Ran off the top of the graph.
        k2start += 2;
      } else if (!front) {
        var k1_offset = v_offset + delta - k2;
        if (k1_offset >= 0 && k1_offset < v_length && v1[k1_offset] != -1) {
          var x1 = v1[k1_offset];
          var y1 = v_offset + x1 - k1_offset;
          // Mirror x2 onto top-left coordinate system.
          x2 = text1_length - x2;
          if (x1 >= x2) {
            // Overlap detected.
            return this.diff_bisectSplit_(text1, text2, x1, y1, deadline);
          }
        }
      }
    }
  }
  // Diff took too long and hit the deadline or
  // number of diffs equals number of characters, no commonality at all.
  return [new diff_match_patch.Diff(DIFF_DELETE, text1), new diff_match_patch.Diff(DIFF_INSERT, text2)];
};

/**
 * Given the location of the 'middle snake', split the diff in two parts
 * and recurse.
 * @param {string} text1 Old string to be diffed.
 * @param {string} text2 New string to be diffed.
 * @param {number} x Index of split point in text1.
 * @param {number} y Index of split point in text2.
 * @param {number} deadline Time at which to bail if not yet complete.
 * @return {!Array.<!diff_match_patch.Diff>} Array of diff tuples.
 * @private
 */
diff_match_patch.prototype.diff_bisectSplit_ = function (text1, text2, x, y, deadline) {
  var text1a = text1.substring(0, x);
  var text2a = text2.substring(0, y);
  var text1b = text1.substring(x);
  var text2b = text2.substring(y);

  // Compute both diffs serially.
  var diffs = this.diff_main(text1a, text2a, false, deadline);
  var diffsb = this.diff_main(text1b, text2b, false, deadline);
  return diffs.concat(diffsb);
};

/**
 * Split two texts into an array of strings.  Reduce the texts to a string of
 * hashes where each Unicode character represents one line.
 * @param {string} text1 First string.
 * @param {string} text2 Second string.
 * @return {{chars1: string, chars2: string, lineArray: !Array.<string>}}
 *     An object containing the encoded text1, the encoded text2 and
 *     the array of unique strings.
 *     The zeroth element of the array of unique strings is intentionally blank.
 * @private
 */
diff_match_patch.prototype.diff_linesToChars_ = function (text1, text2) {
  var lineArray = []; // e.g. lineArray[4] == 'Hello\n'
  var lineHash = {}; // e.g. lineHash['Hello\n'] == 4

  // '\x00' is a valid character, but various debuggers don't like it.
  // So we'll insert a junk entry to avoid generating a null character.
  lineArray[0] = '';

  /**
   * Split a text into an array of strings.  Reduce the texts to a string of
   * hashes where each Unicode character represents one line.
   * Modifies linearray and linehash through being a closure.
   * @param {string} text String to encode.
   * @return {string} Encoded string.
   * @private
   */
  function diff_linesToCharsMunge_(text) {
    var chars = '';
    // Walk the text, pulling out a substring for each line.
    // text.split('\n') would would temporarily double our memory footprint.
    // Modifying text would create many large strings to garbage collect.
    var lineStart = 0;
    var lineEnd = -1;
    // Keeping our own length variable is faster than looking it up.
    var lineArrayLength = lineArray.length;
    while (lineEnd < text.length - 1) {
      lineEnd = text.indexOf('\n', lineStart);
      if (lineEnd == -1) {
        lineEnd = text.length - 1;
      }
      var line = text.substring(lineStart, lineEnd + 1);
      if (lineHash.hasOwnProperty ? lineHash.hasOwnProperty(line) : lineHash[line] !== undefined) {
        chars += String.fromCharCode(lineHash[line]);
      } else {
        if (lineArrayLength == maxLines) {
          // Bail out at 65535 because
          // String.fromCharCode(65536) == String.fromCharCode(0)
          line = text.substring(lineStart);
          lineEnd = text.length;
        }
        chars += String.fromCharCode(lineArrayLength);
        lineHash[line] = lineArrayLength;
        lineArray[lineArrayLength++] = line;
      }
      lineStart = lineEnd + 1;
    }
    return chars;
  }
  // Allocate 2/3rds of the space for text1, the rest for text2.
  var maxLines = 40000;
  var chars1 = diff_linesToCharsMunge_(text1);
  maxLines = 65535;
  var chars2 = diff_linesToCharsMunge_(text2);
  return {
    chars1: chars1,
    chars2: chars2,
    lineArray: lineArray
  };
};

/**
 * Rehydrate the text in a diff from a string of line hashes to real lines of
 * text.
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 * @param {!Array.<string>} lineArray Array of unique strings.
 * @private
 */
diff_match_patch.prototype.diff_charsToLines_ = function (diffs, lineArray) {
  for (var i = 0; i < diffs.length; i++) {
    var chars = diffs[i][1];
    var text = [];
    for (var j = 0; j < chars.length; j++) {
      text[j] = lineArray[chars.charCodeAt(j)];
    }
    diffs[i][1] = text.join('');
  }
};

/**
 * Determine the common prefix of two strings.
 * @param {string} text1 First string.
 * @param {string} text2 Second string.
 * @return {number} The number of characters common to the start of each
 *     string.
 */
diff_match_patch.prototype.diff_commonPrefix = function (text1, text2) {
  // Quick check for common null cases.
  if (!text1 || !text2 || text1.charAt(0) != text2.charAt(0)) {
    return 0;
  }
  // Binary search.
  // Performance analysis: https://neil.fraser.name/news/2007/10/09/
  var pointermin = 0;
  var pointermax = Math.min(text1.length, text2.length);
  var pointermid = pointermax;
  var pointerstart = 0;
  while (pointermin < pointermid) {
    if (text1.substring(pointerstart, pointermid) == text2.substring(pointerstart, pointermid)) {
      pointermin = pointermid;
      pointerstart = pointermin;
    } else {
      pointermax = pointermid;
    }
    pointermid = Math.floor((pointermax - pointermin) / 2 + pointermin);
  }
  return pointermid;
};

/**
 * Determine the common suffix of two strings.
 * @param {string} text1 First string.
 * @param {string} text2 Second string.
 * @return {number} The number of characters common to the end of each string.
 */
diff_match_patch.prototype.diff_commonSuffix = function (text1, text2) {
  // Quick check for common null cases.
  if (!text1 || !text2 || text1.charAt(text1.length - 1) != text2.charAt(text2.length - 1)) {
    return 0;
  }
  // Binary search.
  // Performance analysis: https://neil.fraser.name/news/2007/10/09/
  var pointermin = 0;
  var pointermax = Math.min(text1.length, text2.length);
  var pointermid = pointermax;
  var pointerend = 0;
  while (pointermin < pointermid) {
    if (text1.substring(text1.length - pointermid, text1.length - pointerend) == text2.substring(text2.length - pointermid, text2.length - pointerend)) {
      pointermin = pointermid;
      pointerend = pointermin;
    } else {
      pointermax = pointermid;
    }
    pointermid = Math.floor((pointermax - pointermin) / 2 + pointermin);
  }
  return pointermid;
};

/**
 * Determine if the suffix of one string is the prefix of another.
 * @param {string} text1 First string.
 * @param {string} text2 Second string.
 * @return {number} The number of characters common to the end of the first
 *     string and the start of the second string.
 * @private
 */
diff_match_patch.prototype.diff_commonOverlap_ = function (text1, text2) {
  // Cache the text lengths to prevent multiple calls.
  var text1_length = text1.length;
  var text2_length = text2.length;
  // Eliminate the null case.
  if (text1_length == 0 || text2_length == 0) {
    return 0;
  }
  // Truncate the longer string.
  if (text1_length > text2_length) {
    text1 = text1.substring(text1_length - text2_length);
  } else if (text1_length < text2_length) {
    text2 = text2.substring(0, text1_length);
  }
  var text_length = Math.min(text1_length, text2_length);
  // Quick check for the worst case.
  if (text1 == text2) {
    return text_length;
  }

  // Start by looking for a single character match
  // and increase length until no match is found.
  // Performance analysis: https://neil.fraser.name/news/2010/11/04/
  var best = 0;
  var length = 1;
  while (true) {
    var pattern = text1.substring(text_length - length);
    var found = text2.indexOf(pattern);
    if (found == -1) {
      return best;
    }
    length += found;
    if (found == 0 || text1.substring(text_length - length) == text2.substring(0, length)) {
      best = length;
      length++;
    }
  }
};

/**
 * Do the two texts share a substring which is at least half the length of the
 * longer text?
 * This speedup can produce non-minimal diffs.
 * @param {string} text1 First string.
 * @param {string} text2 Second string.
 * @return {Array.<string>} Five element Array, containing the prefix of
 *     text1, the suffix of text1, the prefix of text2, the suffix of
 *     text2 and the common middle.  Or null if there was no match.
 * @private
 */
diff_match_patch.prototype.diff_halfMatch_ = function (text1, text2) {
  if (this.Diff_Timeout <= 0) {
    // Don't risk returning a non-optimal diff if we have unlimited time.
    return null;
  }
  var longtext = text1.length > text2.length ? text1 : text2;
  var shorttext = text1.length > text2.length ? text2 : text1;
  if (longtext.length < 4 || shorttext.length * 2 < longtext.length) {
    return null; // Pointless.
  }
  var dmp = this; // 'this' becomes 'window' in a closure.

  /**
   * Does a substring of shorttext exist within longtext such that the substring
   * is at least half the length of longtext?
   * Closure, but does not reference any external variables.
   * @param {string} longtext Longer string.
   * @param {string} shorttext Shorter string.
   * @param {number} i Start index of quarter length substring within longtext.
   * @return {Array.<string>} Five element Array, containing the prefix of
   *     longtext, the suffix of longtext, the prefix of shorttext, the suffix
   *     of shorttext and the common middle.  Or null if there was no match.
   * @private
   */
  function diff_halfMatchI_(longtext, shorttext, i) {
    // Start with a 1/4 length substring at position i as a seed.
    var seed = longtext.substring(i, i + Math.floor(longtext.length / 4));
    var j = -1;
    var best_common = '';
    var best_longtext_a, best_longtext_b, best_shorttext_a, best_shorttext_b;
    while ((j = shorttext.indexOf(seed, j + 1)) != -1) {
      var prefixLength = dmp.diff_commonPrefix(longtext.substring(i), shorttext.substring(j));
      var suffixLength = dmp.diff_commonSuffix(longtext.substring(0, i), shorttext.substring(0, j));
      if (best_common.length < suffixLength + prefixLength) {
        best_common = shorttext.substring(j - suffixLength, j) + shorttext.substring(j, j + prefixLength);
        best_longtext_a = longtext.substring(0, i - suffixLength);
        best_longtext_b = longtext.substring(i + prefixLength);
        best_shorttext_a = shorttext.substring(0, j - suffixLength);
        best_shorttext_b = shorttext.substring(j + prefixLength);
      }
    }
    if (best_common.length * 2 >= longtext.length) {
      return [best_longtext_a, best_longtext_b, best_shorttext_a, best_shorttext_b, best_common];
    } else {
      return null;
    }
  }

  // First check if the second quarter is the seed for a half-match.
  var hm1 = diff_halfMatchI_(longtext, shorttext, Math.ceil(longtext.length / 4));
  // Check again based on the third quarter.
  var hm2 = diff_halfMatchI_(longtext, shorttext, Math.ceil(longtext.length / 2));
  var hm;
  if (!hm1 && !hm2) {
    return null;
  } else if (!hm2) {
    hm = hm1;
  } else if (!hm1) {
    hm = hm2;
  } else {
    // Both matched.  Select the longest.
    hm = hm1[4].length > hm2[4].length ? hm1 : hm2;
  }

  // A half-match was found, sort out the return data.
  var text1_a, text1_b, text2_a, text2_b;
  if (text1.length > text2.length) {
    text1_a = hm[0];
    text1_b = hm[1];
    text2_a = hm[2];
    text2_b = hm[3];
  } else {
    text2_a = hm[0];
    text2_b = hm[1];
    text1_a = hm[2];
    text1_b = hm[3];
  }
  var mid_common = hm[4];
  return [text1_a, text1_b, text2_a, text2_b, mid_common];
};

/**
 * Reduce the number of edits by eliminating semantically trivial equalities.
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 */
diff_match_patch.prototype.diff_cleanupSemantic = function (diffs) {
  var changes = false;
  var equalities = []; // Stack of indices where equalities are found.
  var equalitiesLength = 0; // Keeping our own length var is faster in JS.
  /** @type {?string} */
  var lastEquality = null;
  // Always equal to diffs[equalities[equalitiesLength - 1]][1]
  var pointer = 0; // Index of current position.
  // Number of characters that changed prior to the equality.
  var length_insertions1 = 0;
  var length_deletions1 = 0;
  // Number of characters that changed after the equality.
  var length_insertions2 = 0;
  var length_deletions2 = 0;
  while (pointer < diffs.length) {
    if (diffs[pointer][0] == DIFF_EQUAL) {
      // Equality found.
      equalities[equalitiesLength++] = pointer;
      length_insertions1 = length_insertions2;
      length_deletions1 = length_deletions2;
      length_insertions2 = 0;
      length_deletions2 = 0;
      lastEquality = diffs[pointer][1];
    } else {
      // An insertion or deletion.
      if (diffs[pointer][0] == DIFF_INSERT) {
        length_insertions2 += diffs[pointer][1].length;
      } else {
        length_deletions2 += diffs[pointer][1].length;
      }
      // Eliminate an equality that is smaller or equal to the edits on both
      // sides of it.
      if (lastEquality && lastEquality.length <= Math.max(length_insertions1, length_deletions1) && lastEquality.length <= Math.max(length_insertions2, length_deletions2)) {
        // Duplicate record.
        diffs.splice(equalities[equalitiesLength - 1], 0, new diff_match_patch.Diff(DIFF_DELETE, lastEquality));
        // Change second copy to insert.
        diffs[equalities[equalitiesLength - 1] + 1][0] = DIFF_INSERT;
        // Throw away the equality we just deleted.
        equalitiesLength--;
        // Throw away the previous equality (it needs to be reevaluated).
        equalitiesLength--;
        pointer = equalitiesLength > 0 ? equalities[equalitiesLength - 1] : -1;
        length_insertions1 = 0; // Reset the counters.
        length_deletions1 = 0;
        length_insertions2 = 0;
        length_deletions2 = 0;
        lastEquality = null;
        changes = true;
      }
    }
    pointer++;
  }

  // Normalize the diff.
  if (changes) {
    this.diff_cleanupMerge(diffs);
  }
  this.diff_cleanupSemanticLossless(diffs);

  // Find any overlaps between deletions and insertions.
  // e.g: <del>abcxxx</del><ins>xxxdef</ins>
  //   -> <del>abc</del>xxx<ins>def</ins>
  // e.g: <del>xxxabc</del><ins>defxxx</ins>
  //   -> <ins>def</ins>xxx<del>abc</del>
  // Only extract an overlap if it is as big as the edit ahead or behind it.
  pointer = 1;
  while (pointer < diffs.length) {
    if (diffs[pointer - 1][0] == DIFF_DELETE && diffs[pointer][0] == DIFF_INSERT) {
      var deletion = diffs[pointer - 1][1];
      var insertion = diffs[pointer][1];
      var overlap_length1 = this.diff_commonOverlap_(deletion, insertion);
      var overlap_length2 = this.diff_commonOverlap_(insertion, deletion);
      if (overlap_length1 >= overlap_length2) {
        if (overlap_length1 >= deletion.length / 2 || overlap_length1 >= insertion.length / 2) {
          // Overlap found.  Insert an equality and trim the surrounding edits.
          diffs.splice(pointer, 0, new diff_match_patch.Diff(DIFF_EQUAL, insertion.substring(0, overlap_length1)));
          diffs[pointer - 1][1] = deletion.substring(0, deletion.length - overlap_length1);
          diffs[pointer + 1][1] = insertion.substring(overlap_length1);
          pointer++;
        }
      } else {
        if (overlap_length2 >= deletion.length / 2 || overlap_length2 >= insertion.length / 2) {
          // Reverse overlap found.
          // Insert an equality and swap and trim the surrounding edits.
          diffs.splice(pointer, 0, new diff_match_patch.Diff(DIFF_EQUAL, deletion.substring(0, overlap_length2)));
          diffs[pointer - 1][0] = DIFF_INSERT;
          diffs[pointer - 1][1] = insertion.substring(0, insertion.length - overlap_length2);
          diffs[pointer + 1][0] = DIFF_DELETE;
          diffs[pointer + 1][1] = deletion.substring(overlap_length2);
          pointer++;
        }
      }
      pointer++;
    }
    pointer++;
  }
};

/**
 * Look for single edits surrounded on both sides by equalities
 * which can be shifted sideways to align the edit to a word boundary.
 * e.g: The c<ins>at c</ins>ame. -> The <ins>cat </ins>came.
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 */
diff_match_patch.prototype.diff_cleanupSemanticLossless = function (diffs) {
  /**
   * Given two strings, compute a score representing whether the internal
   * boundary falls on logical boundaries.
   * Scores range from 6 (best) to 0 (worst).
   * Closure, but does not reference any external variables.
   * @param {string} one First string.
   * @param {string} two Second string.
   * @return {number} The score.
   * @private
   */
  function diff_cleanupSemanticScore_(one, two) {
    if (!one || !two) {
      // Edges are the best.
      return 6;
    }

    // Each port of this function behaves slightly differently due to
    // subtle differences in each language's definition of things like
    // 'whitespace'.  Since this function's purpose is largely cosmetic,
    // the choice has been made to use each language's native features
    // rather than force total conformity.
    var char1 = one.charAt(one.length - 1);
    var char2 = two.charAt(0);
    var nonAlphaNumeric1 = char1.match(diff_match_patch.nonAlphaNumericRegex_);
    var nonAlphaNumeric2 = char2.match(diff_match_patch.nonAlphaNumericRegex_);
    var whitespace1 = nonAlphaNumeric1 && char1.match(diff_match_patch.whitespaceRegex_);
    var whitespace2 = nonAlphaNumeric2 && char2.match(diff_match_patch.whitespaceRegex_);
    var lineBreak1 = whitespace1 && char1.match(diff_match_patch.linebreakRegex_);
    var lineBreak2 = whitespace2 && char2.match(diff_match_patch.linebreakRegex_);
    var blankLine1 = lineBreak1 && one.match(diff_match_patch.blanklineEndRegex_);
    var blankLine2 = lineBreak2 && two.match(diff_match_patch.blanklineStartRegex_);
    if (blankLine1 || blankLine2) {
      // Five points for blank lines.
      return 5;
    } else if (lineBreak1 || lineBreak2) {
      // Four points for line breaks.
      return 4;
    } else if (nonAlphaNumeric1 && !whitespace1 && whitespace2) {
      // Three points for end of sentences.
      return 3;
    } else if (whitespace1 || whitespace2) {
      // Two points for whitespace.
      return 2;
    } else if (nonAlphaNumeric1 || nonAlphaNumeric2) {
      // One point for non-alphanumeric.
      return 1;
    }
    return 0;
  }
  var pointer = 1;
  // Intentionally ignore the first and last element (don't need checking).
  while (pointer < diffs.length - 1) {
    if (diffs[pointer - 1][0] == DIFF_EQUAL && diffs[pointer + 1][0] == DIFF_EQUAL) {
      // This is a single edit surrounded by equalities.
      var equality1 = diffs[pointer - 1][1];
      var edit = diffs[pointer][1];
      var equality2 = diffs[pointer + 1][1];

      // First, shift the edit as far left as possible.
      var commonOffset = this.diff_commonSuffix(equality1, edit);
      if (commonOffset) {
        var commonString = edit.substring(edit.length - commonOffset);
        equality1 = equality1.substring(0, equality1.length - commonOffset);
        edit = commonString + edit.substring(0, edit.length - commonOffset);
        equality2 = commonString + equality2;
      }

      // Second, step character by character right, looking for the best fit.
      var bestEquality1 = equality1;
      var bestEdit = edit;
      var bestEquality2 = equality2;
      var bestScore = diff_cleanupSemanticScore_(equality1, edit) + diff_cleanupSemanticScore_(edit, equality2);
      while (edit.charAt(0) === equality2.charAt(0)) {
        equality1 += edit.charAt(0);
        edit = edit.substring(1) + equality2.charAt(0);
        equality2 = equality2.substring(1);
        var score = diff_cleanupSemanticScore_(equality1, edit) + diff_cleanupSemanticScore_(edit, equality2);
        // The >= encourages trailing rather than leading whitespace on edits.
        if (score >= bestScore) {
          bestScore = score;
          bestEquality1 = equality1;
          bestEdit = edit;
          bestEquality2 = equality2;
        }
      }
      if (diffs[pointer - 1][1] != bestEquality1) {
        // We have an improvement, save it back to the diff.
        if (bestEquality1) {
          diffs[pointer - 1][1] = bestEquality1;
        } else {
          diffs.splice(pointer - 1, 1);
          pointer--;
        }
        diffs[pointer][1] = bestEdit;
        if (bestEquality2) {
          diffs[pointer + 1][1] = bestEquality2;
        } else {
          diffs.splice(pointer + 1, 1);
          pointer--;
        }
      }
    }
    pointer++;
  }
};

// Define some regex patterns for matching boundaries.
diff_match_patch.nonAlphaNumericRegex_ = /[^a-zA-Z0-9]/;
diff_match_patch.whitespaceRegex_ = /\s/;
diff_match_patch.linebreakRegex_ = /[\r\n]/;
diff_match_patch.blanklineEndRegex_ = /\n\r?\n$/;
diff_match_patch.blanklineStartRegex_ = /^\r?\n\r?\n/;

/**
 * Reduce the number of edits by eliminating operationally trivial equalities.
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 */
diff_match_patch.prototype.diff_cleanupEfficiency = function (diffs) {
  var changes = false;
  var equalities = []; // Stack of indices where equalities are found.
  var equalitiesLength = 0; // Keeping our own length var is faster in JS.
  /** @type {?string} */
  var lastEquality = null;
  // Always equal to diffs[equalities[equalitiesLength - 1]][1]
  var pointer = 0; // Index of current position.
  // Is there an insertion operation before the last equality.
  var pre_ins = false;
  // Is there a deletion operation before the last equality.
  var pre_del = false;
  // Is there an insertion operation after the last equality.
  var post_ins = false;
  // Is there a deletion operation after the last equality.
  var post_del = false;
  while (pointer < diffs.length) {
    if (diffs[pointer][0] == DIFF_EQUAL) {
      // Equality found.
      if (diffs[pointer][1].length < this.Diff_EditCost && (post_ins || post_del)) {
        // Candidate found.
        equalities[equalitiesLength++] = pointer;
        pre_ins = post_ins;
        pre_del = post_del;
        lastEquality = diffs[pointer][1];
      } else {
        // Not a candidate, and can never become one.
        equalitiesLength = 0;
        lastEquality = null;
      }
      post_ins = post_del = false;
    } else {
      // An insertion or deletion.
      if (diffs[pointer][0] == DIFF_DELETE) {
        post_del = true;
      } else {
        post_ins = true;
      }
      /*
       * Five types to be split:
       * <ins>A</ins><del>B</del>XY<ins>C</ins><del>D</del>
       * <ins>A</ins>X<ins>C</ins><del>D</del>
       * <ins>A</ins><del>B</del>X<ins>C</ins>
       * <ins>A</del>X<ins>C</ins><del>D</del>
       * <ins>A</ins><del>B</del>X<del>C</del>
       */
      if (lastEquality && (pre_ins && pre_del && post_ins && post_del || lastEquality.length < this.Diff_EditCost / 2 && pre_ins + pre_del + post_ins + post_del == 3)) {
        // Duplicate record.
        diffs.splice(equalities[equalitiesLength - 1], 0, new diff_match_patch.Diff(DIFF_DELETE, lastEquality));
        // Change second copy to insert.
        diffs[equalities[equalitiesLength - 1] + 1][0] = DIFF_INSERT;
        equalitiesLength--; // Throw away the equality we just deleted;
        lastEquality = null;
        if (pre_ins && pre_del) {
          // No changes made which could affect previous entry, keep going.
          post_ins = post_del = true;
          equalitiesLength = 0;
        } else {
          equalitiesLength--; // Throw away the previous equality.
          pointer = equalitiesLength > 0 ? equalities[equalitiesLength - 1] : -1;
          post_ins = post_del = false;
        }
        changes = true;
      }
    }
    pointer++;
  }
  if (changes) {
    this.diff_cleanupMerge(diffs);
  }
};

/**
 * Reorder and merge like edit sections.  Merge equalities.
 * Any edit section can move as long as it doesn't cross an equality.
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 */
diff_match_patch.prototype.diff_cleanupMerge = function (diffs) {
  // Add a dummy entry at the end.
  diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, ''));
  var pointer = 0;
  var count_delete = 0;
  var count_insert = 0;
  var text_delete = '';
  var text_insert = '';
  var commonlength;
  while (pointer < diffs.length) {
    switch (diffs[pointer][0]) {
      case DIFF_INSERT:
        count_insert++;
        text_insert += diffs[pointer][1];
        pointer++;
        break;
      case DIFF_DELETE:
        count_delete++;
        text_delete += diffs[pointer][1];
        pointer++;
        break;
      case DIFF_EQUAL:
        // Upon reaching an equality, check for prior redundancies.
        if (count_delete + count_insert > 1) {
          if (count_delete !== 0 && count_insert !== 0) {
            // Factor out any common prefixies.
            commonlength = this.diff_commonPrefix(text_insert, text_delete);
            if (commonlength !== 0) {
              if (pointer - count_delete - count_insert > 0 && diffs[pointer - count_delete - count_insert - 1][0] == DIFF_EQUAL) {
                diffs[pointer - count_delete - count_insert - 1][1] += text_insert.substring(0, commonlength);
              } else {
                diffs.splice(0, 0, new diff_match_patch.Diff(DIFF_EQUAL, text_insert.substring(0, commonlength)));
                pointer++;
              }
              text_insert = text_insert.substring(commonlength);
              text_delete = text_delete.substring(commonlength);
            }
            // Factor out any common suffixies.
            commonlength = this.diff_commonSuffix(text_insert, text_delete);
            if (commonlength !== 0) {
              diffs[pointer][1] = text_insert.substring(text_insert.length - commonlength) + diffs[pointer][1];
              text_insert = text_insert.substring(0, text_insert.length - commonlength);
              text_delete = text_delete.substring(0, text_delete.length - commonlength);
            }
          }
          // Delete the offending records and add the merged ones.
          pointer -= count_delete + count_insert;
          diffs.splice(pointer, count_delete + count_insert);
          if (text_delete.length) {
            diffs.splice(pointer, 0, new diff_match_patch.Diff(DIFF_DELETE, text_delete));
            pointer++;
          }
          if (text_insert.length) {
            diffs.splice(pointer, 0, new diff_match_patch.Diff(DIFF_INSERT, text_insert));
            pointer++;
          }
          pointer++;
        } else if (pointer !== 0 && diffs[pointer - 1][0] == DIFF_EQUAL) {
          // Merge this equality with the previous one.
          diffs[pointer - 1][1] += diffs[pointer][1];
          diffs.splice(pointer, 1);
        } else {
          pointer++;
        }
        count_insert = 0;
        count_delete = 0;
        text_delete = '';
        text_insert = '';
        break;
    }
  }
  if (diffs[diffs.length - 1][1] === '') {
    diffs.pop(); // Remove the dummy entry at the end.
  }

  // Second pass: look for single edits surrounded on both sides by equalities
  // which can be shifted sideways to eliminate an equality.
  // e.g: A<ins>BA</ins>C -> <ins>AB</ins>AC
  var changes = false;
  pointer = 1;
  // Intentionally ignore the first and last element (don't need checking).
  while (pointer < diffs.length - 1) {
    if (diffs[pointer - 1][0] == DIFF_EQUAL && diffs[pointer + 1][0] == DIFF_EQUAL) {
      // This is a single edit surrounded by equalities.
      if (diffs[pointer][1].substring(diffs[pointer][1].length - diffs[pointer - 1][1].length) == diffs[pointer - 1][1]) {
        // Shift the edit over the previous equality.
        diffs[pointer][1] = diffs[pointer - 1][1] + diffs[pointer][1].substring(0, diffs[pointer][1].length - diffs[pointer - 1][1].length);
        diffs[pointer + 1][1] = diffs[pointer - 1][1] + diffs[pointer + 1][1];
        diffs.splice(pointer - 1, 1);
        changes = true;
      } else if (diffs[pointer][1].substring(0, diffs[pointer + 1][1].length) == diffs[pointer + 1][1]) {
        // Shift the edit over the next equality.
        diffs[pointer - 1][1] += diffs[pointer + 1][1];
        diffs[pointer][1] = diffs[pointer][1].substring(diffs[pointer + 1][1].length) + diffs[pointer + 1][1];
        diffs.splice(pointer + 1, 1);
        changes = true;
      }
    }
    pointer++;
  }
  // If shifts were made, the diff needs reordering and another shift sweep.
  if (changes) {
    this.diff_cleanupMerge(diffs);
  }
};

/**
 * loc is a location in text1, compute and return the equivalent location in
 * text2.
 * e.g. 'The cat' vs 'The big cat', 1->1, 5->8
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 * @param {number} loc Location within text1.
 * @return {number} Location within text2.
 */
diff_match_patch.prototype.diff_xIndex = function (diffs, loc) {
  var chars1 = 0;
  var chars2 = 0;
  var last_chars1 = 0;
  var last_chars2 = 0;
  var x;
  for (x = 0; x < diffs.length; x++) {
    if (diffs[x][0] !== DIFF_INSERT) {
      // Equality or deletion.
      chars1 += diffs[x][1].length;
    }
    if (diffs[x][0] !== DIFF_DELETE) {
      // Equality or insertion.
      chars2 += diffs[x][1].length;
    }
    if (chars1 > loc) {
      // Overshot the location.
      break;
    }
    last_chars1 = chars1;
    last_chars2 = chars2;
  }
  // Was the location was deleted?
  if (diffs.length != x && diffs[x][0] === DIFF_DELETE) {
    return last_chars2;
  }
  // Add the remaining character length.
  return last_chars2 + (loc - last_chars1);
};

/**
 * Convert a diff array into a pretty HTML report.
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 * @return {string} HTML representation.
 */
diff_match_patch.prototype.diff_prettyHtml = function (diffs) {
  var html = [];
  var pattern_amp = /&/g;
  var pattern_lt = /</g;
  var pattern_gt = />/g;
  var pattern_para = /\n/g;
  for (var x = 0; x < diffs.length; x++) {
    var op = diffs[x][0]; // Operation (insert, delete, equal)
    var data = diffs[x][1]; // Text of change.
    var text = data.replace(pattern_amp, '&amp;').replace(pattern_lt, '&lt;').replace(pattern_gt, '&gt;').replace(pattern_para, '&para;<br>');
    switch (op) {
      case DIFF_INSERT:
        html[x] = '<ins style="background:#e6ffe6;">' + text + '</ins>';
        break;
      case DIFF_DELETE:
        html[x] = '<del style="background:#ffe6e6;">' + text + '</del>';
        break;
      case DIFF_EQUAL:
        html[x] = '<span>' + text + '</span>';
        break;
    }
  }
  return html.join('');
};

/**
 * Compute and return the source text (all equalities and deletions).
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 * @return {string} Source text.
 */
diff_match_patch.prototype.diff_text1 = function (diffs) {
  var text = [];
  for (var x = 0; x < diffs.length; x++) {
    if (diffs[x][0] !== DIFF_INSERT) {
      text[x] = diffs[x][1];
    }
  }
  return text.join('');
};

/**
 * Compute and return the destination text (all equalities and insertions).
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 * @return {string} Destination text.
 */
diff_match_patch.prototype.diff_text2 = function (diffs) {
  var text = [];
  for (var x = 0; x < diffs.length; x++) {
    if (diffs[x][0] !== DIFF_DELETE) {
      text[x] = diffs[x][1];
    }
  }
  return text.join('');
};

/**
 * Compute the Levenshtein distance; the number of inserted, deleted or
 * substituted characters.
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 * @return {number} Number of changes.
 */
diff_match_patch.prototype.diff_levenshtein = function (diffs) {
  var levenshtein = 0;
  var insertions = 0;
  var deletions = 0;
  for (var x = 0; x < diffs.length; x++) {
    var op = diffs[x][0];
    var data = diffs[x][1];
    switch (op) {
      case DIFF_INSERT:
        insertions += data.length;
        break;
      case DIFF_DELETE:
        deletions += data.length;
        break;
      case DIFF_EQUAL:
        // A deletion and an insertion is one substitution.
        levenshtein += Math.max(insertions, deletions);
        insertions = 0;
        deletions = 0;
        break;
    }
  }
  levenshtein += Math.max(insertions, deletions);
  return levenshtein;
};

/**
 * Crush the diff into an encoded string which describes the operations
 * required to transform text1 into text2.
 * E.g. =3\t-2\t+ing  -> Keep 3 chars, delete 2 chars, insert 'ing'.
 * Operations are tab-separated.  Inserted text is escaped using %xx notation.
 * @param {!Array.<!diff_match_patch.Diff>} diffs Array of diff tuples.
 * @return {string} Delta text.
 */
diff_match_patch.prototype.diff_toDelta = function (diffs) {
  var text = [];
  for (var x = 0; x < diffs.length; x++) {
    switch (diffs[x][0]) {
      case DIFF_INSERT:
        text[x] = '+' + encodeURI(diffs[x][1]);
        break;
      case DIFF_DELETE:
        text[x] = '-' + diffs[x][1].length;
        break;
      case DIFF_EQUAL:
        text[x] = '=' + diffs[x][1].length;
        break;
    }
  }
  return text.join('\t').replace(/%20/g, ' ');
};

/**
 * Given the original text1, and an encoded string which describes the
 * operations required to transform text1 into text2, compute the full diff.
 * @param {string} text1 Source string for the diff.
 * @param {string} delta Delta text.
 * @return {!Array.<!diff_match_patch.Diff>} Array of diff tuples.
 * @throws {!Error} If invalid input.
 */
diff_match_patch.prototype.diff_fromDelta = function (text1, delta) {
  var diffs = [];
  var diffsLength = 0; // Keeping our own length var is faster in JS.
  var pointer = 0; // Cursor in text1
  var tokens = delta.split(/\t/g);
  for (var x = 0; x < tokens.length; x++) {
    // Each token begins with a one character parameter which specifies the
    // operation of this token (delete, insert, equality).
    var param = tokens[x].substring(1);
    switch (tokens[x].charAt(0)) {
      case '+':
        try {
          diffs[diffsLength++] = new diff_match_patch.Diff(DIFF_INSERT, decodeURI(param));
        } catch (ex) {
          // Malformed URI sequence.
          throw new Error('Illegal escape in diff_fromDelta: ' + param);
        }
        break;
      case '-':
      // Fall through.
      case '=':
        var n = parseInt(param, 10);
        if (isNaN(n) || n < 0) {
          throw new Error('Invalid number in diff_fromDelta: ' + param);
        }
        var text = text1.substring(pointer, pointer += n);
        if (tokens[x].charAt(0) == '=') {
          diffs[diffsLength++] = new diff_match_patch.Diff(DIFF_EQUAL, text);
        } else {
          diffs[diffsLength++] = new diff_match_patch.Diff(DIFF_DELETE, text);
        }
        break;
      default:
        // Blank tokens are ok (from a trailing \t).
        // Anything else is an error.
        if (tokens[x]) {
          throw new Error('Invalid diff operation in diff_fromDelta: ' + tokens[x]);
        }
    }
  }
  if (pointer != text1.length) {
    throw new Error('Delta length (' + pointer + ') does not equal source text length (' + text1.length + ').');
  }
  return diffs;
};

//  MATCH FUNCTIONS

/**
 * Locate the best instance of 'pattern' in 'text' near 'loc'.
 * @param {string} text The text to search.
 * @param {string} pattern The pattern to search for.
 * @param {number} loc The location to search around.
 * @return {number} Best match index or -1.
 */
diff_match_patch.prototype.match_main = function (text, pattern, loc) {
  // Check for null inputs.
  if (text == null || pattern == null || loc == null) {
    throw new Error('Null input. (match_main)');
  }
  loc = Math.max(0, Math.min(loc, text.length));
  if (text == pattern) {
    // Shortcut (potentially not guaranteed by the algorithm)
    return 0;
  } else if (!text.length) {
    // Nothing to match.
    return -1;
  } else if (text.substring(loc, loc + pattern.length) == pattern) {
    // Perfect match at the perfect spot!  (Includes case of null pattern)
    return loc;
  } else {
    // Do a fuzzy compare.
    return this.match_bitap_(text, pattern, loc);
  }
};

/**
 * Locate the best instance of 'pattern' in 'text' near 'loc' using the
 * Bitap algorithm.
 * @param {string} text The text to search.
 * @param {string} pattern The pattern to search for.
 * @param {number} loc The location to search around.
 * @return {number} Best match index or -1.
 * @private
 */
diff_match_patch.prototype.match_bitap_ = function (text, pattern, loc) {
  if (pattern.length > this.Match_MaxBits) {
    throw new Error('Pattern too long for this browser.');
  }

  // Initialise the alphabet.
  var s = this.match_alphabet_(pattern);
  var dmp = this; // 'this' becomes 'window' in a closure.

  /**
   * Compute and return the score for a match with e errors and x location.
   * Accesses loc and pattern through being a closure.
   * @param {number} e Number of errors in match.
   * @param {number} x Location of match.
   * @return {number} Overall score for match (0.0 = good, 1.0 = bad).
   * @private
   */
  function match_bitapScore_(e, x) {
    var accuracy = e / pattern.length;
    var proximity = Math.abs(loc - x);
    if (!dmp.Match_Distance) {
      // Dodge divide by zero error.
      return proximity ? 1.0 : accuracy;
    }
    return accuracy + proximity / dmp.Match_Distance;
  }

  // Highest score beyond which we give up.
  var score_threshold = this.Match_Threshold;
  // Is there a nearby exact match? (speedup)
  var best_loc = text.indexOf(pattern, loc);
  if (best_loc != -1) {
    score_threshold = Math.min(match_bitapScore_(0, best_loc), score_threshold);
    // What about in the other direction? (speedup)
    best_loc = text.lastIndexOf(pattern, loc + pattern.length);
    if (best_loc != -1) {
      score_threshold = Math.min(match_bitapScore_(0, best_loc), score_threshold);
    }
  }

  // Initialise the bit arrays.
  var matchmask = 1 << pattern.length - 1;
  best_loc = -1;
  var bin_min, bin_mid;
  var bin_max = pattern.length + text.length;
  var last_rd;
  for (var d = 0; d < pattern.length; d++) {
    // Scan for the best match; each iteration allows for one more error.
    // Run a binary search to determine how far from 'loc' we can stray at this
    // error level.
    bin_min = 0;
    bin_mid = bin_max;
    while (bin_min < bin_mid) {
      if (match_bitapScore_(d, loc + bin_mid) <= score_threshold) {
        bin_min = bin_mid;
      } else {
        bin_max = bin_mid;
      }
      bin_mid = Math.floor((bin_max - bin_min) / 2 + bin_min);
    }
    // Use the result from this iteration as the maximum for the next.
    bin_max = bin_mid;
    var start = Math.max(1, loc - bin_mid + 1);
    var finish = Math.min(loc + bin_mid, text.length) + pattern.length;
    var rd = Array(finish + 2);
    rd[finish + 1] = (1 << d) - 1;
    for (var j = finish; j >= start; j--) {
      // The alphabet (s) is a sparse hash, so the following line generates
      // warnings.
      var charMatch = s[text.charAt(j - 1)];
      if (d === 0) {
        // First pass: exact match.
        rd[j] = (rd[j + 1] << 1 | 1) & charMatch;
      } else {
        // Subsequent passes: fuzzy match.
        rd[j] = (rd[j + 1] << 1 | 1) & charMatch | ((last_rd[j + 1] | last_rd[j]) << 1 | 1) | last_rd[j + 1];
      }
      if (rd[j] & matchmask) {
        var score = match_bitapScore_(d, j - 1);
        // This match will almost certainly be better than any existing match.
        // But check anyway.
        if (score <= score_threshold) {
          // Told you so.
          score_threshold = score;
          best_loc = j - 1;
          if (best_loc > loc) {
            // When passing loc, don't exceed our current distance from loc.
            start = Math.max(1, 2 * loc - best_loc);
          } else {
            // Already passed loc, downhill from here on in.
            break;
          }
        }
      }
    }
    // No hope for a (better) match at greater error levels.
    if (match_bitapScore_(d + 1, loc) > score_threshold) {
      break;
    }
    last_rd = rd;
  }
  return best_loc;
};

/**
 * Initialise the alphabet for the Bitap algorithm.
 * @param {string} pattern The text to encode.
 * @return {!Object} Hash of character locations.
 * @private
 */
diff_match_patch.prototype.match_alphabet_ = function (pattern) {
  var s = {};
  for (var i = 0; i < pattern.length; i++) {
    s[pattern.charAt(i)] = 0;
  }
  for (var i = 0; i < pattern.length; i++) {
    s[pattern.charAt(i)] |= 1 << pattern.length - i - 1;
  }
  return s;
};

//  PATCH FUNCTIONS

/**
 * Increase the context until it is unique,
 * but don't let the pattern expand beyond Match_MaxBits.
 * @param {!diff_match_patch.patch_obj} patch The patch to grow.
 * @param {string} text Source text.
 * @private
 */
diff_match_patch.prototype.patch_addContext_ = function (patch, text) {
  if (text.length == 0) {
    return;
  }
  if (patch.start2 === null) {
    throw Error('patch not initialized');
  }
  var pattern = text.substring(patch.start2, patch.start2 + patch.length1);
  var padding = 0;

  // Look for the first and last matches of pattern in text.  If two different
  // matches are found, increase the pattern length.
  while (text.indexOf(pattern) != text.lastIndexOf(pattern) && pattern.length < this.Match_MaxBits - this.Patch_Margin - this.Patch_Margin) {
    padding += this.Patch_Margin;
    pattern = text.substring(patch.start2 - padding, patch.start2 + patch.length1 + padding);
  }
  // Add one chunk for good luck.
  padding += this.Patch_Margin;

  // Add the prefix.
  var prefix = text.substring(patch.start2 - padding, patch.start2);
  if (prefix) {
    patch.diffs.unshift(new diff_match_patch.Diff(DIFF_EQUAL, prefix));
  }
  // Add the suffix.
  var suffix = text.substring(patch.start2 + patch.length1, patch.start2 + patch.length1 + padding);
  if (suffix) {
    patch.diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, suffix));
  }

  // Roll back the start points.
  patch.start1 -= prefix.length;
  patch.start2 -= prefix.length;
  // Extend the lengths.
  patch.length1 += prefix.length + suffix.length;
  patch.length2 += prefix.length + suffix.length;
};

/**
 * Compute a list of patches to turn text1 into text2.
 * Use diffs if provided, otherwise compute it ourselves.
 * There are four ways to call this function, depending on what data is
 * available to the caller:
 * Method 1:
 * a = text1, b = text2
 * Method 2:
 * a = diffs
 * Method 3 (optimal):
 * a = text1, b = diffs
 * Method 4 (deprecated, use method 3):
 * a = text1, b = text2, c = diffs
 *
 * @param {string|!Array.<!diff_match_patch.Diff>} a text1 (methods 1,3,4) or
 * Array of diff tuples for text1 to text2 (method 2).
 * @param {string|!Array.<!diff_match_patch.Diff>=} opt_b text2 (methods 1,4) or
 * Array of diff tuples for text1 to text2 (method 3) or undefined (method 2).
 * @param {string|!Array.<!diff_match_patch.Diff>=} opt_c Array of diff tuples
 * for text1 to text2 (method 4) or undefined (methods 1,2,3).
 * @return {!Array.<!diff_match_patch.patch_obj>} Array of Patch objects.
 */
diff_match_patch.prototype.patch_make = function (a, opt_b, opt_c) {
  var text1, diffs;
  if (typeof a == 'string' && typeof opt_b == 'string' && typeof opt_c == 'undefined') {
    // Method 1: text1, text2
    // Compute diffs from text1 and text2.
    text1 = /** @type {string} */a;
    diffs = this.diff_main(text1, /** @type {string} */opt_b, true);
    if (diffs.length > 2) {
      this.diff_cleanupSemantic(diffs);
      this.diff_cleanupEfficiency(diffs);
    }
  } else if (a && typeof a == 'object' && typeof opt_b == 'undefined' && typeof opt_c == 'undefined') {
    // Method 2: diffs
    // Compute text1 from diffs.
    diffs = /** @type {!Array.<!diff_match_patch.Diff>} */a;
    text1 = this.diff_text1(diffs);
  } else if (typeof a == 'string' && opt_b && typeof opt_b == 'object' && typeof opt_c == 'undefined') {
    // Method 3: text1, diffs
    text1 = /** @type {string} */a;
    diffs = /** @type {!Array.<!diff_match_patch.Diff>} */opt_b;
  } else if (typeof a == 'string' && typeof opt_b == 'string' && opt_c && typeof opt_c == 'object') {
    // Method 4: text1, text2, diffs
    // text2 is not used.
    text1 = /** @type {string} */a;
    diffs = /** @type {!Array.<!diff_match_patch.Diff>} */opt_c;
  } else {
    throw new Error('Unknown call format to patch_make.');
  }
  if (diffs.length === 0) {
    return []; // Get rid of the null case.
  }
  var patches = [];
  var patch = new diff_match_patch.patch_obj();
  var patchDiffLength = 0; // Keeping our own length var is faster in JS.
  var char_count1 = 0; // Number of characters into the text1 string.
  var char_count2 = 0; // Number of characters into the text2 string.
  // Start with text1 (prepatch_text) and apply the diffs until we arrive at
  // text2 (postpatch_text).  We recreate the patches one by one to determine
  // context info.
  var prepatch_text = text1;
  var postpatch_text = text1;
  for (var x = 0; x < diffs.length; x++) {
    var diff_type = diffs[x][0];
    var diff_text = diffs[x][1];
    if (!patchDiffLength && diff_type !== DIFF_EQUAL) {
      // A new patch starts here.
      patch.start1 = char_count1;
      patch.start2 = char_count2;
    }
    switch (diff_type) {
      case DIFF_INSERT:
        patch.diffs[patchDiffLength++] = diffs[x];
        patch.length2 += diff_text.length;
        postpatch_text = postpatch_text.substring(0, char_count2) + diff_text + postpatch_text.substring(char_count2);
        break;
      case DIFF_DELETE:
        patch.length1 += diff_text.length;
        patch.diffs[patchDiffLength++] = diffs[x];
        postpatch_text = postpatch_text.substring(0, char_count2) + postpatch_text.substring(char_count2 + diff_text.length);
        break;
      case DIFF_EQUAL:
        if (diff_text.length <= 2 * this.Patch_Margin && patchDiffLength && diffs.length != x + 1) {
          // Small equality inside a patch.
          patch.diffs[patchDiffLength++] = diffs[x];
          patch.length1 += diff_text.length;
          patch.length2 += diff_text.length;
        } else if (diff_text.length >= 2 * this.Patch_Margin) {
          // Time for a new patch.
          if (patchDiffLength) {
            this.patch_addContext_(patch, prepatch_text);
            patches.push(patch);
            patch = new diff_match_patch.patch_obj();
            patchDiffLength = 0;
            // Unlike Unidiff, our patch lists have a rolling context.
            // https://github.com/google/diff-match-patch/wiki/Unidiff
            // Update prepatch text & pos to reflect the application of the
            // just completed patch.
            prepatch_text = postpatch_text;
            char_count1 = char_count2;
          }
        }
        break;
    }

    // Update the current character count.
    if (diff_type !== DIFF_INSERT) {
      char_count1 += diff_text.length;
    }
    if (diff_type !== DIFF_DELETE) {
      char_count2 += diff_text.length;
    }
  }
  // Pick up the leftover patch if not empty.
  if (patchDiffLength) {
    this.patch_addContext_(patch, prepatch_text);
    patches.push(patch);
  }
  return patches;
};

/**
 * Given an array of patches, return another array that is identical.
 * @param {!Array.<!diff_match_patch.patch_obj>} patches Array of Patch objects.
 * @return {!Array.<!diff_match_patch.patch_obj>} Array of Patch objects.
 */
diff_match_patch.prototype.patch_deepCopy = function (patches) {
  // Making deep copies is hard in JavaScript.
  var patchesCopy = [];
  for (var x = 0; x < patches.length; x++) {
    var patch = patches[x];
    var patchCopy = new diff_match_patch.patch_obj();
    patchCopy.diffs = [];
    for (var y = 0; y < patch.diffs.length; y++) {
      patchCopy.diffs[y] = new diff_match_patch.Diff(patch.diffs[y][0], patch.diffs[y][1]);
    }
    patchCopy.start1 = patch.start1;
    patchCopy.start2 = patch.start2;
    patchCopy.length1 = patch.length1;
    patchCopy.length2 = patch.length2;
    patchesCopy[x] = patchCopy;
  }
  return patchesCopy;
};

/**
 * Merge a set of patches onto the text.  Return a patched text, as well
 * as a list of true/false values indicating which patches were applied.
 * @param {!Array.<!diff_match_patch.patch_obj>} patches Array of Patch objects.
 * @param {string} text Old text.
 * @return {!Array.<string|!Array.<boolean>>} Two element Array, containing the
 *      new text and an array of boolean values.
 */
diff_match_patch.prototype.patch_apply = function (patches, text) {
  if (patches.length == 0) {
    return [text, []];
  }

  // Deep copy the patches so that no changes are made to originals.
  patches = this.patch_deepCopy(patches);
  var nullPadding = this.patch_addPadding(patches);
  text = nullPadding + text + nullPadding;
  this.patch_splitMax(patches);
  // delta keeps track of the offset between the expected and actual location
  // of the previous patch.  If there are patches expected at positions 10 and
  // 20, but the first patch was found at 12, delta is 2 and the second patch
  // has an effective expected position of 22.
  var delta = 0;
  var results = [];
  for (var x = 0; x < patches.length; x++) {
    var expected_loc = patches[x].start2 + delta;
    var text1 = this.diff_text1(patches[x].diffs);
    var start_loc;
    var end_loc = -1;
    if (text1.length > this.Match_MaxBits) {
      // patch_splitMax will only provide an oversized pattern in the case of
      // a monster delete.
      start_loc = this.match_main(text, text1.substring(0, this.Match_MaxBits), expected_loc);
      if (start_loc != -1) {
        end_loc = this.match_main(text, text1.substring(text1.length - this.Match_MaxBits), expected_loc + text1.length - this.Match_MaxBits);
        if (end_loc == -1 || start_loc >= end_loc) {
          // Can't find valid trailing context.  Drop this patch.
          start_loc = -1;
        }
      }
    } else {
      start_loc = this.match_main(text, text1, expected_loc);
    }
    if (start_loc == -1) {
      // No match found.  :(
      results[x] = false;
      // Subtract the delta for this failed patch from subsequent patches.
      delta -= patches[x].length2 - patches[x].length1;
    } else {
      // Found a match.  :)
      results[x] = true;
      delta = start_loc - expected_loc;
      var text2;
      if (end_loc == -1) {
        text2 = text.substring(start_loc, start_loc + text1.length);
      } else {
        text2 = text.substring(start_loc, end_loc + this.Match_MaxBits);
      }
      if (text1 == text2) {
        // Perfect match, just shove the replacement text in.
        text = text.substring(0, start_loc) + this.diff_text2(patches[x].diffs) + text.substring(start_loc + text1.length);
      } else {
        // Imperfect match.  Run a diff to get a framework of equivalent
        // indices.
        var diffs = this.diff_main(text1, text2, false);
        if (text1.length > this.Match_MaxBits && this.diff_levenshtein(diffs) / text1.length > this.Patch_DeleteThreshold) {
          // The end points match, but the content is unacceptably bad.
          results[x] = false;
        } else {
          this.diff_cleanupSemanticLossless(diffs);
          var index1 = 0;
          var index2;
          for (var y = 0; y < patches[x].diffs.length; y++) {
            var mod = patches[x].diffs[y];
            if (mod[0] !== DIFF_EQUAL) {
              index2 = this.diff_xIndex(diffs, index1);
            }
            if (mod[0] === DIFF_INSERT) {
              // Insertion
              text = text.substring(0, start_loc + index2) + mod[1] + text.substring(start_loc + index2);
            } else if (mod[0] === DIFF_DELETE) {
              // Deletion
              text = text.substring(0, start_loc + index2) + text.substring(start_loc + this.diff_xIndex(diffs, index1 + mod[1].length));
            }
            if (mod[0] !== DIFF_DELETE) {
              index1 += mod[1].length;
            }
          }
        }
      }
    }
  }
  // Strip the padding off.
  text = text.substring(nullPadding.length, text.length - nullPadding.length);
  return [text, results];
};

/**
 * Add some padding on text start and end so that edges can match something.
 * Intended to be called only from within patch_apply.
 * @param {!Array.<!diff_match_patch.patch_obj>} patches Array of Patch objects.
 * @return {string} The padding string added to each side.
 */
diff_match_patch.prototype.patch_addPadding = function (patches) {
  var paddingLength = this.Patch_Margin;
  var nullPadding = '';
  for (var x = 1; x <= paddingLength; x++) {
    nullPadding += String.fromCharCode(x);
  }

  // Bump all the patches forward.
  for (var x = 0; x < patches.length; x++) {
    patches[x].start1 += paddingLength;
    patches[x].start2 += paddingLength;
  }

  // Add some padding on start of first diff.
  var patch = patches[0];
  var diffs = patch.diffs;
  if (diffs.length == 0 || diffs[0][0] != DIFF_EQUAL) {
    // Add nullPadding equality.
    diffs.unshift(new diff_match_patch.Diff(DIFF_EQUAL, nullPadding));
    patch.start1 -= paddingLength; // Should be 0.
    patch.start2 -= paddingLength; // Should be 0.
    patch.length1 += paddingLength;
    patch.length2 += paddingLength;
  } else if (paddingLength > diffs[0][1].length) {
    // Grow first equality.
    var extraLength = paddingLength - diffs[0][1].length;
    diffs[0][1] = nullPadding.substring(diffs[0][1].length) + diffs[0][1];
    patch.start1 -= extraLength;
    patch.start2 -= extraLength;
    patch.length1 += extraLength;
    patch.length2 += extraLength;
  }

  // Add some padding on end of last diff.
  patch = patches[patches.length - 1];
  diffs = patch.diffs;
  if (diffs.length == 0 || diffs[diffs.length - 1][0] != DIFF_EQUAL) {
    // Add nullPadding equality.
    diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, nullPadding));
    patch.length1 += paddingLength;
    patch.length2 += paddingLength;
  } else if (paddingLength > diffs[diffs.length - 1][1].length) {
    // Grow last equality.
    var extraLength = paddingLength - diffs[diffs.length - 1][1].length;
    diffs[diffs.length - 1][1] += nullPadding.substring(0, extraLength);
    patch.length1 += extraLength;
    patch.length2 += extraLength;
  }
  return nullPadding;
};

/**
 * Look through the patches and break up any which are longer than the maximum
 * limit of the match algorithm.
 * Intended to be called only from within patch_apply.
 * @param {!Array.<!diff_match_patch.patch_obj>} patches Array of Patch objects.
 */
diff_match_patch.prototype.patch_splitMax = function (patches) {
  var patch_size = this.Match_MaxBits;
  for (var x = 0; x < patches.length; x++) {
    if (patches[x].length1 <= patch_size) {
      continue;
    }
    var bigpatch = patches[x];
    // Remove the big old patch.
    patches.splice(x--, 1);
    var start1 = bigpatch.start1;
    var start2 = bigpatch.start2;
    var precontext = '';
    while (bigpatch.diffs.length !== 0) {
      // Create one of several smaller patches.
      var patch = new diff_match_patch.patch_obj();
      var empty = true;
      patch.start1 = start1 - precontext.length;
      patch.start2 = start2 - precontext.length;
      if (precontext !== '') {
        patch.length1 = patch.length2 = precontext.length;
        patch.diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, precontext));
      }
      while (bigpatch.diffs.length !== 0 && patch.length1 < patch_size - this.Patch_Margin) {
        var diff_type = bigpatch.diffs[0][0];
        var diff_text = bigpatch.diffs[0][1];
        if (diff_type === DIFF_INSERT) {
          // Insertions are harmless.
          patch.length2 += diff_text.length;
          start2 += diff_text.length;
          patch.diffs.push(bigpatch.diffs.shift());
          empty = false;
        } else if (diff_type === DIFF_DELETE && patch.diffs.length == 1 && patch.diffs[0][0] == DIFF_EQUAL && diff_text.length > 2 * patch_size) {
          // This is a large deletion.  Let it pass in one chunk.
          patch.length1 += diff_text.length;
          start1 += diff_text.length;
          empty = false;
          patch.diffs.push(new diff_match_patch.Diff(diff_type, diff_text));
          bigpatch.diffs.shift();
        } else {
          // Deletion or equality.  Only take as much as we can stomach.
          diff_text = diff_text.substring(0, patch_size - patch.length1 - this.Patch_Margin);
          patch.length1 += diff_text.length;
          start1 += diff_text.length;
          if (diff_type === DIFF_EQUAL) {
            patch.length2 += diff_text.length;
            start2 += diff_text.length;
          } else {
            empty = false;
          }
          patch.diffs.push(new diff_match_patch.Diff(diff_type, diff_text));
          if (diff_text == bigpatch.diffs[0][1]) {
            bigpatch.diffs.shift();
          } else {
            bigpatch.diffs[0][1] = bigpatch.diffs[0][1].substring(diff_text.length);
          }
        }
      }
      // Compute the head context for the next patch.
      precontext = this.diff_text2(patch.diffs);
      precontext = precontext.substring(precontext.length - this.Patch_Margin);
      // Append the end context for this patch.
      var postcontext = this.diff_text1(bigpatch.diffs).substring(0, this.Patch_Margin);
      if (postcontext !== '') {
        patch.length1 += postcontext.length;
        patch.length2 += postcontext.length;
        if (patch.diffs.length !== 0 && patch.diffs[patch.diffs.length - 1][0] === DIFF_EQUAL) {
          patch.diffs[patch.diffs.length - 1][1] += postcontext;
        } else {
          patch.diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, postcontext));
        }
      }
      if (!empty) {
        patches.splice(++x, 0, patch);
      }
    }
  }
};

/**
 * Take a list of patches and return a textual representation.
 * @param {!Array.<!diff_match_patch.patch_obj>} patches Array of Patch objects.
 * @return {string} Text representation of patches.
 */
diff_match_patch.prototype.patch_toText = function (patches) {
  var text = [];
  for (var x = 0; x < patches.length; x++) {
    text[x] = patches[x];
  }
  return text.join('');
};

/**
 * Parse a textual representation of patches and return a list of Patch objects.
 * @param {string} textline Text representation of patches.
 * @return {!Array.<!diff_match_patch.patch_obj>} Array of Patch objects.
 * @throws {!Error} If invalid input.
 */
diff_match_patch.prototype.patch_fromText = function (textline) {
  var patches = [];
  if (!textline) {
    return patches;
  }
  var text = textline.split('\n');
  var textPointer = 0;
  var patchHeader = /^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@$/;
  while (textPointer < text.length) {
    var m = text[textPointer].match(patchHeader);
    if (!m) {
      throw new Error('Invalid patch string: ' + text[textPointer]);
    }
    var patch = new diff_match_patch.patch_obj();
    patches.push(patch);
    patch.start1 = parseInt(m[1], 10);
    if (m[2] === '') {
      patch.start1--;
      patch.length1 = 1;
    } else if (m[2] == '0') {
      patch.length1 = 0;
    } else {
      patch.start1--;
      patch.length1 = parseInt(m[2], 10);
    }
    patch.start2 = parseInt(m[3], 10);
    if (m[4] === '') {
      patch.start2--;
      patch.length2 = 1;
    } else if (m[4] == '0') {
      patch.length2 = 0;
    } else {
      patch.start2--;
      patch.length2 = parseInt(m[4], 10);
    }
    textPointer++;
    while (textPointer < text.length) {
      var sign = text[textPointer].charAt(0);
      try {
        var line = decodeURI(text[textPointer].substring(1));
      } catch (ex) {
        // Malformed URI sequence.
        throw new Error('Illegal escape in patch_fromText: ' + line);
      }
      if (sign == '-') {
        // Deletion.
        patch.diffs.push(new diff_match_patch.Diff(DIFF_DELETE, line));
      } else if (sign == '+') {
        // Insertion.
        patch.diffs.push(new diff_match_patch.Diff(DIFF_INSERT, line));
      } else if (sign == ' ') {
        // Minor equality.
        patch.diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, line));
      } else if (sign == '@') {
        // Start of next patch.
        break;
      } else if (sign === '') {
        // Blank line?  Whatever.
      } else {
        // WTF?
        throw new Error('Invalid patch mode "' + sign + '" in: ' + line);
      }
      textPointer++;
    }
  }
  return patches;
};

/**
 * Class representing one patch operation.
 * @constructor
 */
diff_match_patch.patch_obj = function () {
  /** @type {!Array.<!diff_match_patch.Diff>} */
  this.diffs = [];
  /** @type {?number} */
  this.start1 = null;
  /** @type {?number} */
  this.start2 = null;
  /** @type {number} */
  this.length1 = 0;
  /** @type {number} */
  this.length2 = 0;
};

/**
 * Emulate GNU diff's format.
 * Header: @@ -382,8 +481,9 @@
 * Indices are printed as 1-based, not 0-based.
 * @return {string} The GNU diff string.
 */
diff_match_patch.patch_obj.prototype.toString = function () {
  var coords1, coords2;
  if (this.length1 === 0) {
    coords1 = this.start1 + ',0';
  } else if (this.length1 == 1) {
    coords1 = this.start1 + 1;
  } else {
    coords1 = this.start1 + 1 + ',' + this.length1;
  }
  if (this.length2 === 0) {
    coords2 = this.start2 + ',0';
  } else if (this.length2 == 1) {
    coords2 = this.start2 + 1;
  } else {
    coords2 = this.start2 + 1 + ',' + this.length2;
  }
  var text = ['@@ -' + coords1 + ' +' + coords2 + ' @@\n'];
  var op;
  // Escape the body of the patch with %xx notation.
  for (var x = 0; x < this.diffs.length; x++) {
    switch (this.diffs[x][0]) {
      case DIFF_INSERT:
        op = '+';
        break;
      case DIFF_DELETE:
        op = '-';
        break;
      case DIFF_EQUAL:
        op = ' ';
        break;
    }
    text[x + 1] = op + encodeURI(this.diffs[x][1]) + '\n';
  }
  return text.join('').replace(/%20/g, ' ');
};

// The following export code was added by @ForbesLindesay
module.exports = diff_match_patch;
module.exports.diff_match_patch = diff_match_patch;
module.exports.DIFF_DELETE = DIFF_DELETE;
module.exports.DIFF_INSERT = DIFF_INSERT;
module.exports.DIFF_EQUAL = DIFF_EQUAL;

/***/ }),

/***/ 664:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";

// EXPORTS
__webpack_require__.d(__webpack_exports__, {
  "default": () => (/* binding */ method)
});

// EXTERNAL MODULE: ./src/ts/markdown/abcRender.ts
var abcRender = __webpack_require__(386);
// EXTERNAL MODULE: ./src/ts/markdown/adapterRender.ts
var adapterRender = __webpack_require__(781);
// EXTERNAL MODULE: ./src/ts/markdown/chartRender.ts
var chartRender = __webpack_require__(379);
// EXTERNAL MODULE: ./src/ts/markdown/codeRender.ts
var codeRender = __webpack_require__(895);
// EXTERNAL MODULE: ./src/ts/markdown/flowchartRender.ts
var flowchartRender = __webpack_require__(169);
// EXTERNAL MODULE: ./src/ts/markdown/graphvizRender.ts
var graphvizRender = __webpack_require__(572);
// EXTERNAL MODULE: ./src/ts/markdown/highlightRender.ts
var highlightRender = __webpack_require__(702);
;// CONCATENATED MODULE: ./src/ts/markdown/lazyLoadImageRender.ts
var lazyLoadImageRender = function (element) {
    if (element === void 0) { element = document; }
    var loadImg = function (it) {
        var testImage = document.createElement("img");
        testImage.src = it.getAttribute("data-src");
        testImage.addEventListener("load", function () {
            if (!it.getAttribute("style") && !it.getAttribute("class") &&
                !it.getAttribute("width") && !it.getAttribute("height")) {
                if (testImage.naturalHeight > testImage.naturalWidth &&
                    testImage.naturalWidth / testImage.naturalHeight <
                        document.querySelector(".vditor-reset").clientWidth / (window.innerHeight - 40) &&
                    testImage.naturalHeight > (window.innerHeight - 40)) {
                    it.style.height = (window.innerHeight - 40) + "px";
                }
            }
            it.src = testImage.src;
        });
        it.removeAttribute("data-src");
    };
    if (!("IntersectionObserver" in window)) {
        element.querySelectorAll("img").forEach(function (imgElement) {
            if (imgElement.getAttribute("data-src")) {
                loadImg(imgElement);
            }
        });
        return false;
    }
    if (window.vditorImageIntersectionObserver) {
        window.vditorImageIntersectionObserver.disconnect();
        element.querySelectorAll("img").forEach(function (imgElement) {
            window.vditorImageIntersectionObserver.observe(imgElement);
        });
    }
    else {
        window.vditorImageIntersectionObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entrie) {
                if ((typeof entrie.isIntersecting === "undefined"
                    ? entrie.intersectionRatio !== 0
                    : entrie.isIntersecting)
                    && entrie.target.getAttribute("data-src")) {
                    loadImg(entrie.target);
                }
            });
        });
        element.querySelectorAll("img").forEach(function (imgElement) {
            window.vditorImageIntersectionObserver.observe(imgElement);
        });
    }
};

// EXTERNAL MODULE: ./src/ts/markdown/mathRender.ts
var mathRender = __webpack_require__(982);
// EXTERNAL MODULE: ./src/ts/markdown/mediaRender.ts
var mediaRender = __webpack_require__(431);
// EXTERNAL MODULE: ./src/ts/markdown/mermaidRender.ts
var mermaidRender = __webpack_require__(570);
// EXTERNAL MODULE: ./src/ts/markdown/markmapRender.ts
var markmapRender = __webpack_require__(593);
// EXTERNAL MODULE: ./src/ts/markdown/mindmapRender.ts
var mindmapRender = __webpack_require__(558);
// EXTERNAL MODULE: ./src/ts/markdown/outlineRender.ts
var outlineRender = __webpack_require__(182);
// EXTERNAL MODULE: ./src/ts/markdown/plantumlRender.ts
var plantumlRender = __webpack_require__(931);
// EXTERNAL MODULE: ./src/ts/constants.ts
var constants = __webpack_require__(793);
// EXTERNAL MODULE: ./src/ts/ui/setContentTheme.ts
var setContentTheme = __webpack_require__(652);
// EXTERNAL MODULE: ./src/ts/util/addScript.ts
var addScript = __webpack_require__(998);
// EXTERNAL MODULE: ./src/ts/util/hasClosest.ts
var hasClosest = __webpack_require__(118);
// EXTERNAL MODULE: ./src/ts/util/merge.ts
var merge = __webpack_require__(2);
;// CONCATENATED MODULE: ./src/ts/markdown/anchorRender.ts
var anchorRender = function (type) {
    document.querySelectorAll(".vditor-anchor").forEach(function (anchor) {
        if (type === 1) {
            anchor.classList.add("vditor-anchor--left");
        }
        anchor.onclick = function () {
            var id = anchor.getAttribute("href").substr(1);
            var top = document.getElementById("vditorAnchor-" + id).offsetTop;
            document.querySelector("html").scrollTop = top;
        };
    });
    window.onhashchange = function () {
        var element = document.getElementById("vditorAnchor-" + decodeURIComponent(window.location.hash.substr(1)));
        if (element) {
            document.querySelector("html").scrollTop = element.offsetTop;
        }
    };
};

// EXTERNAL MODULE: ./src/ts/markdown/setLute.ts
var setLute = __webpack_require__(65);
// EXTERNAL MODULE: ./src/ts/util/selection.ts
var selection = __webpack_require__(307);
;// CONCATENATED MODULE: ./src/ts/markdown/speechRender.ts

var speechRender = function (element, lang) {
    if (lang === void 0) { lang = "zh_CN"; }
    if (typeof speechSynthesis === "undefined" || typeof SpeechSynthesisUtterance === "undefined") {
        return;
    }
    var getVoice = function () {
        var voices = speechSynthesis.getVoices();
        var currentVoice;
        var defaultVoice;
        voices.forEach(function (item) {
            if (item.lang === lang.replace("_", "-")) {
                currentVoice = item;
            }
            if (item.default) {
                defaultVoice = item;
            }
        });
        if (!currentVoice) {
            currentVoice = defaultVoice;
        }
        return currentVoice;
    };
    var playSVG = '<svg><use xlink:href="#vditor-icon-play"></use></svg>';
    var pauseSVG = '<svg><use xlink:href="#vditor-icon-pause"></use></svg>';
    if (!document.getElementById("vditorIconScript")) {
        playSVG = '<svg viewBox="0 0 32 32"><path d="M3.436 0l25.128 16-25.128 16v-32z"></path></svg>';
        pauseSVG = '<svg viewBox="0 0 32 32"><path d="M20.617 0h9.128v32h-9.128v-32zM2.255 32v-32h9.128v32h-9.128z"></path></svg>';
    }
    var speechDom = document.querySelector(".vditor-speech");
    if (!speechDom) {
        speechDom = document.createElement("button");
        speechDom.className = "vditor-speech";
        element.insertAdjacentElement("beforeend", speechDom);
        if (speechSynthesis.onvoiceschanged !== undefined) {
            speechSynthesis.onvoiceschanged = getVoice;
        }
    }
    var voice = getVoice();
    var utterThis = new SpeechSynthesisUtterance();
    utterThis.voice = voice;
    utterThis.onend = utterThis.onerror = function () {
        speechDom.style.display = "none";
        speechSynthesis.cancel();
        speechDom.classList.remove("vditor-speech--current");
        speechDom.innerHTML = playSVG;
    };
    element.addEventListener(window.ontouchstart !== undefined ? "touchend" : "click", function (event) {
        var target = event.target;
        if (target.classList.contains("vditor-speech") || target.parentElement.classList.contains("vditor-speech")) {
            if (!speechDom.classList.contains("vditor-speech--current")) {
                utterThis.text = speechDom.getAttribute("data-text");
                speechSynthesis.speak(utterThis);
                speechDom.classList.add("vditor-speech--current");
                speechDom.innerHTML = pauseSVG;
            }
            else {
                if (speechSynthesis.speaking) {
                    if (speechSynthesis.paused) {
                        speechSynthesis.resume();
                        speechDom.innerHTML = pauseSVG;
                    }
                    else {
                        speechSynthesis.pause();
                        speechDom.innerHTML = playSVG;
                    }
                }
            }
            (0,selection/* setSelectionFocus */.Hc)(window.vditorSpeechRange);
            element.focus();
            return;
        }
        speechDom.style.display = "none";
        speechSynthesis.cancel();
        speechDom.classList.remove("vditor-speech--current");
        speechDom.innerHTML = playSVG;
        if (getSelection().rangeCount === 0) {
            return;
        }
        var range = getSelection().getRangeAt(0);
        var text = range.toString().trim();
        if (!text) {
            return;
        }
        window.vditorSpeechRange = range.cloneRange();
        var rect = range.getBoundingClientRect();
        speechDom.innerHTML = playSVG;
        speechDom.style.display = "block";
        speechDom.style.top = (rect.top + rect.height + document.querySelector("html").scrollTop - 20) + "px";
        if (window.ontouchstart !== undefined) {
            speechDom.style.left = (event.changedTouches[event.changedTouches.length - 1].pageX + 2) + "px";
        }
        else {
            speechDom.style.left = (event.clientX + 2) + "px";
        }
        speechDom.setAttribute("data-text", text);
    });
};

;// CONCATENATED MODULE: ./src/ts/markdown/previewRender.ts
var __awaiter = (undefined && undefined.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (undefined && undefined.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g;
    return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};





















var mergeOptions = function (options) {
    var _a;
    var defaultOption = {
        anchor: 0,
        cdn: constants/* Constants.CDN */.g.CDN,
        customEmoji: {},
        emojiPath: "".concat(constants/* Constants.CDN */.g.CDN, "/dist/images/emoji"),
        hljs: constants/* Constants.HLJS_OPTIONS */.g.HLJS_OPTIONS,
        icon: "ant",
        lang: "zh_CN",
        markdown: constants/* Constants.MARKDOWN_OPTIONS */.g.MARKDOWN_OPTIONS,
        math: constants/* Constants.MATH_OPTIONS */.g.MATH_OPTIONS,
        mode: "light",
        speech: {
            enable: false,
        },
        render: {
            media: {
                enable: true,
            }
        },
        theme: constants/* Constants.THEME_OPTIONS */.g.THEME_OPTIONS,
    };
    if (options.cdn) {
        if (!((_a = options.theme) === null || _a === void 0 ? void 0 : _a.path)) {
            defaultOption.theme.path = "".concat(options.cdn, "/dist/css/content-theme");
        }
        if (!options.emojiPath) {
            defaultOption.emojiPath = "".concat(options.cdn, "/dist/images/emoji");
        }
    }
    return (0,merge/* merge */.T)(defaultOption, options);
};
var md2html = function (mdText, options) {
    var mergedOptions = mergeOptions(options);
    return (0,addScript/* addScript */.G)("".concat(mergedOptions.cdn, "/dist/js/lute/lute.min.js"), "vditorLuteScript").then(function () {
        var lute = (0,setLute/* setLute */.X)({
            autoSpace: mergedOptions.markdown.autoSpace,
            gfmAutoLink: mergedOptions.markdown.gfmAutoLink,
            codeBlockPreview: mergedOptions.markdown.codeBlockPreview,
            emojiSite: mergedOptions.emojiPath,
            emojis: mergedOptions.customEmoji,
            fixTermTypo: mergedOptions.markdown.fixTermTypo,
            footnotes: mergedOptions.markdown.footnotes,
            headingAnchor: mergedOptions.anchor !== 0,
            inlineMathDigit: mergedOptions.math.inlineDigit,
            lazyLoadImage: mergedOptions.lazyLoadImage,
            linkBase: mergedOptions.markdown.linkBase,
            linkPrefix: mergedOptions.markdown.linkPrefix,
            listStyle: mergedOptions.markdown.listStyle,
            mark: mergedOptions.markdown.mark,
            mathBlockPreview: mergedOptions.markdown.mathBlockPreview,
            paragraphBeginningSpace: mergedOptions.markdown.paragraphBeginningSpace,
            sanitize: mergedOptions.markdown.sanitize,
            toc: mergedOptions.markdown.toc,
        });
        if (options === null || options === void 0 ? void 0 : options.renderers) {
            lute.SetJSRenderers({
                renderers: {
                    Md2HTML: options.renderers,
                },
            });
        }
        lute.SetHeadingID(true);
        return lute.Md2HTML(mdText);
    });
};
var previewRender = function (previewElement, markdown, options) { return __awaiter(void 0, void 0, void 0, function () {
    var mergedOptions, html, i18nScriptPrefix, i18nScriptID_1;
    return __generator(this, function (_a) {
        switch (_a.label) {
            case 0:
                mergedOptions = mergeOptions(options);
                return [4 /*yield*/, md2html(markdown, mergedOptions)];
            case 1:
                html = _a.sent();
                if (mergedOptions.transform) {
                    html = mergedOptions.transform(html);
                }
                previewElement.innerHTML = html;
                previewElement.classList.add("vditor-reset");
                if (!!mergedOptions.i18n) return [3 /*break*/, 5];
                if (!!["en_US", "fr_FR", "pt_BR", "ja_JP", "ko_KR", "ru_RU", "sv_SE", "zh_CN", "zh_TW"].includes(mergedOptions.lang)) return [3 /*break*/, 2];
                throw new Error("options.lang error, see https://ld246.com/article/1549638745630#options");
            case 2:
                i18nScriptPrefix = "vditorI18nScript";
                i18nScriptID_1 = i18nScriptPrefix + mergedOptions.lang;
                document.querySelectorAll("head script[id^=\"".concat(i18nScriptPrefix, "\"]")).forEach(function (el) {
                    if (el.id !== i18nScriptID_1) {
                        document.head.removeChild(el);
                    }
                });
                return [4 /*yield*/, (0,addScript/* addScript */.G)("".concat(mergedOptions.cdn, "/dist/js/i18n/").concat(mergedOptions.lang, ".js"), i18nScriptID_1)];
            case 3:
                _a.sent();
                _a.label = 4;
            case 4: return [3 /*break*/, 6];
            case 5:
                window.VditorI18n = mergedOptions.i18n;
                _a.label = 6;
            case 6:
                if (!mergedOptions.icon) return [3 /*break*/, 8];
                return [4 /*yield*/, (0,addScript/* addScript */.G)("".concat(mergedOptions.cdn, "/dist/js/icons/").concat(mergedOptions.icon, ".js"), "vditorIconScript")];
            case 7:
                _a.sent();
                _a.label = 8;
            case 8:
                (0,setContentTheme/* setContentTheme */.Z)(mergedOptions.theme.current, mergedOptions.theme.path);
                if (mergedOptions.anchor === 1) {
                    previewElement.classList.add("vditor-reset--anchor");
                }
                (0,codeRender/* codeRender */.O)(previewElement, mergedOptions.hljs);
                (0,highlightRender/* highlightRender */.s)(mergedOptions.hljs, previewElement, mergedOptions.cdn);
                (0,mathRender/* mathRender */.H)(previewElement, {
                    cdn: mergedOptions.cdn,
                    math: mergedOptions.math,
                });
                (0,mermaidRender/* mermaidRender */.i)(previewElement, mergedOptions.cdn, mergedOptions.mode);
                (0,markmapRender/* markmapRender */.K)(previewElement, mergedOptions.cdn, mergedOptions.mode);
                (0,flowchartRender/* flowchartRender */.P)(previewElement, mergedOptions.cdn);
                (0,graphvizRender/* graphvizRender */.v)(previewElement, mergedOptions.cdn);
                (0,chartRender/* chartRender */.p)(previewElement, mergedOptions.cdn, mergedOptions.mode);
                (0,mindmapRender/* mindmapRender */.P)(previewElement, mergedOptions.cdn, mergedOptions.mode);
                (0,plantumlRender/* plantumlRender */.B)(previewElement, mergedOptions.cdn);
                (0,abcRender/* abcRender */.Q)(previewElement, mergedOptions.cdn);
                if (mergedOptions.render.media.enable) {
                    (0,mediaRender/* mediaRender */.Y)(previewElement);
                }
                if (mergedOptions.speech.enable) {
                    speechRender(previewElement);
                }
                if (mergedOptions.anchor !== 0) {
                    anchorRender(mergedOptions.anchor);
                }
                if (mergedOptions.after) {
                    mergedOptions.after();
                }
                if (mergedOptions.lazyLoadImage) {
                    lazyLoadImageRender(previewElement);
                }
                previewElement.addEventListener("click", function (event) {
                    var spanElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(event.target, "SPAN");
                    if (spanElement && (0,hasClosest/* hasClosestByClassName */.fb)(spanElement, "vditor-toc")) {
                        var headingElement = previewElement.querySelector("#" + spanElement.getAttribute("data-target-id"));
                        if (headingElement) {
                            window.scrollTo(window.scrollX, headingElement.offsetTop);
                        }
                        return;
                    }
                });
                return [2 /*return*/];
        }
    });
}); };

// EXTERNAL MODULE: ./src/ts/preview/image.ts
var preview_image = __webpack_require__(971);
// EXTERNAL MODULE: ./src/ts/ui/setCodeTheme.ts
var setCodeTheme = __webpack_require__(34);
;// CONCATENATED MODULE: ./src/method.ts




















var Vditor = /** @class */ (function () {
    function Vditor() {
    }
    /** 点击图片放大 */
    Vditor.adapterRender = adapterRender;
    /** 点击图片放大 */
    Vditor.previewImage = preview_image/* previewImage */.E;
    /** 为 element 中的代码块添加复制按钮 */
    Vditor.codeRender = codeRender/* codeRender */.O;
    /** 对 graphviz 进行渲染 */
    Vditor.graphvizRender = graphvizRender/* graphvizRender */.v;
    /** 为 element 中的代码块进行高亮渲染 */
    Vditor.highlightRender = highlightRender/* highlightRender */.s;
    /** 对数学公式进行渲染 */
    Vditor.mathRender = mathRender/* mathRender */.H;
    /** 流程图/时序图/甘特图渲染 */
    Vditor.mermaidRender = mermaidRender/* mermaidRender */.i;
    /** 支持markdown的思维导图 */
    Vditor.markmapRender = markmapRender/* markmapRender */.K;
    /** flowchart.js 渲染 */
    Vditor.flowchartRender = flowchartRender/* flowchartRender */.P;
    /** 图表渲染 */
    Vditor.chartRender = chartRender/* chartRender */.p;
    /** 五线谱渲染 */
    Vditor.abcRender = abcRender/* abcRender */.Q;
    /** 脑图渲染 */
    Vditor.mindmapRender = mindmapRender/* mindmapRender */.P;
    /** plantuml渲染 */
    Vditor.plantumlRender = plantumlRender/* plantumlRender */.B;
    /** 大纲渲染 */
    Vditor.outlineRender = outlineRender/* outlineRender */.k;
    /** 为[特定链接](https://github.com/Vanessa219/vditor/issues/7)分别渲染为视频、音频、嵌入的 iframe */
    Vditor.mediaRender = mediaRender/* mediaRender */.Y;
    /** 对选中的文字进行阅读 */
    Vditor.speechRender = speechRender;
    /** 对图片进行懒加载 */
    Vditor.lazyLoadImageRender = lazyLoadImageRender;
    /** Markdown 文本转换为 HTML，该方法需使用[异步编程](https://ld246.com/article/1546828434083?r=Vaness) */
    Vditor.md2html = md2html;
    /** 页面 Markdown 文章渲染 */
    Vditor.preview = previewRender;
    /** 设置代码主题 */
    Vditor.setCodeTheme = setCodeTheme/* setCodeTheme */.Y;
    /** 设置内容主题 */
    Vditor.setContentTheme = setContentTheme/* setContentTheme */.Z;
    return Vditor;
}());
/* harmony default export */ const method = (Vditor);


/***/ }),

/***/ 793:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "H": () => (/* binding */ _VDITOR_VERSION),
/* harmony export */   "g": () => (/* binding */ Constants)
/* harmony export */ });
var _VDITOR_VERSION = "3.10.5";

var Constants = /** @class */ (function () {
    function Constants() {
    }
    Constants.ZWSP = "\u200b";
    Constants.DROP_EDITOR = "application/editor";
    Constants.MOBILE_WIDTH = 520;
    Constants.CLASS_MENU_DISABLED = "vditor-menu--disabled";
    Constants.EDIT_TOOLBARS = ["emoji", "headings", "bold", "italic", "strike", "link", "list",
        "ordered-list", "outdent", "indent", "check", "line", "quote", "code", "inline-code", "insert-after",
        "insert-before", "upload", "record", "table"];
    Constants.CODE_THEME = ["abap", "algol", "algol_nu", "arduino", "autumn", "borland", "bw",
        "colorful", "dracula", "emacs", "friendly", "fruity", "github", "igor", "lovelace", "manni", "monokai",
        "monokailight", "murphy", "native", "paraiso-dark", "paraiso-light", "pastie", "perldoc", "pygments",
        "rainbow_dash", "rrt", "solarized-dark", "solarized-dark256", "solarized-light", "swapoff", "tango", "trac",
        "vim", "vs", "xcode", "ant-design"];
    Constants.CODE_LANGUAGES = ["mermaid", "echarts", "mindmap", "plantuml", "abc", "graphviz", "flowchart", "apache",
        "js", "ts", "html", "markmap",
        // common
        "properties", "apache", "bash", "c", "csharp", "cpp", "css", "coffeescript", "diff", "go", "xml", "http",
        "json", "java", "javascript", "kotlin", "less", "lua", "makefile", "markdown", "nginx", "objectivec", "php",
        "php-template", "perl", "plaintext", "python", "python-repl", "r", "ruby", "rust", "scss", "sql", "shell",
        "swift", "ini", "typescript", "vbnet", "yaml",
        "ada", "clojure", "dart", "erb", "fortran", "gradle", "haskell", "julia", "julia-repl", "lisp", "matlab",
        "pgsql", "powershell", "sql_more", "stata", "cmake", "mathematica",
        // ext
        "solidity", "yul"
    ];
    Constants.CDN = "https://unpkg.com/vditor@".concat("3.10.5");
    Constants.MARKDOWN_OPTIONS = {
        autoSpace: false,
        gfmAutoLink: true,
        codeBlockPreview: true,
        fixTermTypo: false,
        footnotes: true,
        linkBase: "",
        linkPrefix: "",
        listStyle: false,
        mark: false,
        mathBlockPreview: true,
        paragraphBeginningSpace: false,
        sanitize: true,
        toc: false,
    };
    Constants.HLJS_OPTIONS = {
        enable: true,
        lineNumber: false,
        defaultLang: "",
        style: "github",
    };
    Constants.MATH_OPTIONS = {
        engine: "KaTeX",
        inlineDigit: false,
        macros: {},
    };
    Constants.THEME_OPTIONS = {
        current: "light",
        list: {
            "ant-design": "Ant Design",
            "dark": "Dark",
            "light": "Light",
            "wechat": "WeChat",
        },
        path: "".concat(Constants.CDN, "/dist/css/content-theme"),
    };
    return Constants;
}());



/***/ }),

/***/ 386:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "Q": () => (/* binding */ abcRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(998);
/* harmony import */ var _adapterRender__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(781);



var abcRender = function (element, cdn) {
    if (element === void 0) { element = document; }
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    var abcElements = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.abcRenderAdapter.getElements(element);
    if (abcElements.length > 0) {
        (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/abcjs/abcjs_basic.min.js"), "vditorAbcjsScript").then(function () {
            abcElements.forEach(function (item) {
                if (item.parentElement.classList.contains("vditor-wysiwyg__pre") ||
                    item.parentElement.classList.contains("vditor-ir__marker--pre")) {
                    return;
                }
                if (item.getAttribute("data-processed") === "true") {
                    return;
                }
                ABCJS.renderAbc(item, _adapterRender__WEBPACK_IMPORTED_MODULE_1__.abcRenderAdapter.getCode(item).trim());
                item.style.overflowX = "auto";
                item.setAttribute("data-processed", "true");
            });
        });
    }
};


/***/ }),

/***/ 781:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "abcRenderAdapter": () => (/* binding */ abcRenderAdapter),
/* harmony export */   "chartRenderAdapter": () => (/* binding */ chartRenderAdapter),
/* harmony export */   "flowchartRenderAdapter": () => (/* binding */ flowchartRenderAdapter),
/* harmony export */   "graphvizRenderAdapter": () => (/* binding */ graphvizRenderAdapter),
/* harmony export */   "markmapRenderAdapter": () => (/* binding */ markmapRenderAdapter),
/* harmony export */   "mathRenderAdapter": () => (/* binding */ mathRenderAdapter),
/* harmony export */   "mermaidRenderAdapter": () => (/* binding */ mermaidRenderAdapter),
/* harmony export */   "mindmapRenderAdapter": () => (/* binding */ mindmapRenderAdapter),
/* harmony export */   "plantumlRenderAdapter": () => (/* binding */ plantumlRenderAdapter)
/* harmony export */ });
var mathRenderAdapter = {
    getCode: function (mathElement) { return mathElement.textContent; },
    getElements: function (element) { return element.querySelectorAll(".language-math"); },
};
var mermaidRenderAdapter = {
    /** 不仅要返回code，并且需要将 code 设置为 el 的 innerHTML */
    getCode: function (el) { return el.textContent; },
    getElements: function (element) { return element.querySelectorAll(".language-mermaid"); },
};
var markmapRenderAdapter = {
    getCode: function (el) { return el.textContent; },
    getElements: function (element) { return element.querySelectorAll(".language-markmap"); },
};
var mindmapRenderAdapter = {
    getCode: function (el) { return el.getAttribute("data-code"); },
    getElements: function (el) { return el.querySelectorAll(".language-mindmap"); },
};
var chartRenderAdapter = {
    getCode: function (el) { return el.innerText; },
    getElements: function (el) { return el.querySelectorAll(".language-echarts"); },
};
var abcRenderAdapter = {
    getCode: function (el) { return el.textContent; },
    getElements: function (el) { return el.querySelectorAll(".language-abc"); },
};
var graphvizRenderAdapter = {
    getCode: function (el) { return el.textContent; },
    getElements: function (el) { return el.querySelectorAll(".language-graphviz"); },
};
var flowchartRenderAdapter = {
    getCode: function (el) { return el.textContent; },
    getElements: function (el) { return el.querySelectorAll(".language-flowchart"); },
};
var plantumlRenderAdapter = {
    getCode: function (el) { return el.textContent; },
    getElements: function (el) { return el.querySelectorAll(".language-plantuml"); },
};


/***/ }),

/***/ 379:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "p": () => (/* binding */ chartRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(998);
/* harmony import */ var _adapterRender__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(781);



var chartRender = function (element, cdn, theme) {
    if (element === void 0) { element = document; }
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    var echartsElements = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.chartRenderAdapter.getElements(element);
    if (echartsElements.length > 0) {
        (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/echarts/echarts.min.js"), "vditorEchartsScript").then(function () {
            echartsElements.forEach(function (e) {
                if (e.parentElement.classList.contains("vditor-wysiwyg__pre") ||
                    e.parentElement.classList.contains("vditor-ir__marker--pre")) {
                    return;
                }
                var text = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.chartRenderAdapter.getCode(e).trim();
                if (!text) {
                    return;
                }
                try {
                    if (e.getAttribute("data-processed") === "true") {
                        return;
                    }
                    var option = JSON.parse(text);
                    echarts.init(e, theme === "dark" ? "dark" : undefined).setOption(option);
                    e.setAttribute("data-processed", "true");
                }
                catch (error) {
                    e.className = "vditor-reset--error";
                    e.innerHTML = "echarts render error: <br>".concat(error);
                }
            });
        });
    }
};


/***/ }),

/***/ 895:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "O": () => (/* binding */ codeRender)
/* harmony export */ });
/* harmony import */ var _util_code160to32__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(528);
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);


var codeRender = function (element, option) {
    Array.from(element.querySelectorAll("pre > code")).filter(function (e, index) {
        if (e.parentElement.classList.contains("vditor-wysiwyg__pre") ||
            e.parentElement.classList.contains("vditor-ir__marker--pre")) {
            return false;
        }
        if (e.classList.contains("language-mermaid") || e.classList.contains("language-flowchart") ||
            e.classList.contains("language-echarts") || e.classList.contains("language-mindmap") ||
            e.classList.contains("language-plantuml") || e.classList.contains("language-markmap") ||
            e.classList.contains("language-abc") || e.classList.contains("language-graphviz") ||
            e.classList.contains("language-math")) {
            return false;
        }
        if (e.style.maxHeight.indexOf("px") > -1) {
            return false;
        }
        // 避免预览区在渲染后由于代码块过多产生性能问题 https://github.com/b3log/vditor/issues/67
        if (element.classList.contains("vditor-preview") && index > 5) {
            return false;
        }
        return true;
    }).forEach(function (e) {
        var _a, _b, _c;
        var codeText = e.innerText;
        if (e.classList.contains("highlight-chroma")) {
            var codeElement = e.cloneNode(true);
            codeElement.querySelectorAll(".highlight-ln").forEach(function (item) {
                item.remove();
            });
            codeText = codeElement.innerText;
        }
        else if (codeText.endsWith("\n")) {
            codeText = codeText.substr(0, codeText.length - 1);
        }
        var iconHTML = '<svg><use xlink:href="#vditor-icon-copy"></use></svg>';
        if (!document.getElementById("vditorIconScript")) {
            iconHTML = '<svg viewBox="0 0 32 32"><path d="M22.545-0h-17.455c-1.6 0-2.909 1.309-2.909 2.909v20.364h2.909v-20.364h17.455v-2.909zM26.909 5.818h-16c-1.6 0-2.909 1.309-2.909 2.909v20.364c0 1.6 1.309 2.909 2.909 2.909h16c1.6 0 2.909-1.309 2.909-2.909v-20.364c0-1.6-1.309-2.909-2.909-2.909zM26.909 29.091h-16v-20.364h16v20.364z"></path></svg>';
        }
        var divElement = document.createElement("div");
        divElement.className = "vditor-copy";
        divElement.innerHTML = "<span aria-label=\"".concat(((_a = window.VditorI18n) === null || _a === void 0 ? void 0 : _a.copy) || "复制", "\"\nonmouseover=\"this.setAttribute('aria-label', '").concat(((_b = window.VditorI18n) === null || _b === void 0 ? void 0 : _b.copy) || "复制", "')\"\nclass=\"vditor-tooltipped vditor-tooltipped__w\"\nonclick=\"this.previousElementSibling.select();document.execCommand('copy');this.setAttribute('aria-label', '").concat(((_c = window.VditorI18n) === null || _c === void 0 ? void 0 : _c.copied) || "已复制", "');this.previousElementSibling.blur()\">").concat(iconHTML, "</span>");
        var textarea = document.createElement("textarea");
        textarea.value = (0,_util_code160to32__WEBPACK_IMPORTED_MODULE_1__/* .code160to32 */ .X)(codeText);
        divElement.insertAdjacentElement("afterbegin", textarea);
        if (option && option.renderMenu) {
            option.renderMenu(e, divElement);
        }
        e.before(divElement);
        e.style.maxHeight = (window.outerHeight - 40) + "px";
        // https://github.com/Vanessa219/vditor/issues/1356
        e.insertAdjacentHTML("afterend", "<span style=\"position: absolute\">".concat(_constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.ZWSP */ .g.ZWSP, "</span>"));
    });
};


/***/ }),

/***/ 169:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "P": () => (/* binding */ flowchartRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(998);
/* harmony import */ var _adapterRender__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(781);



var flowchartRender = function (element, cdn) {
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    var flowchartElements = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.flowchartRenderAdapter.getElements(element);
    if (flowchartElements.length === 0) {
        return;
    }
    (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/flowchart.js/flowchart.min.js"), "vditorFlowchartScript").then(function () {
        flowchartElements.forEach(function (item) {
            if (item.getAttribute("data-processed") === "true") {
                return;
            }
            var flowchartObj = flowchart.parse(_adapterRender__WEBPACK_IMPORTED_MODULE_1__.flowchartRenderAdapter.getCode(item));
            item.innerHTML = "";
            flowchartObj.drawSVG(item);
            item.setAttribute("data-processed", "true");
        });
    });
};


/***/ }),

/***/ 572:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "v": () => (/* binding */ graphvizRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(998);
/* harmony import */ var _adapterRender__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(781);



var graphvizRender = function (element, cdn) {
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    var graphvizElements = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.graphvizRenderAdapter.getElements(element);
    if (graphvizElements.length === 0) {
        return;
    }
    (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/graphviz/viz.js"), "vditorGraphVizScript").then(function () {
        graphvizElements.forEach(function (e) {
            var code = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.graphvizRenderAdapter.getCode(e);
            if (e.parentElement.classList.contains("vditor-wysiwyg__pre") ||
                e.parentElement.classList.contains("vditor-ir__marker--pre")) {
                return;
            }
            if (e.getAttribute("data-processed") === "true" || code.trim() === "") {
                return;
            }
            try {
                var blob = new Blob(["importScripts('".concat(document.getElementById("vditorGraphVizScript").src.replace("viz.js", "full.render.js"), "');")], { type: "application/javascript" });
                var url = window.URL || window.webkitURL;
                var blobUrl = url.createObjectURL(blob);
                var worker = new Worker(blobUrl);
                new Viz({ worker: worker })
                    .renderSVGElement(code).then(function (result) {
                    e.innerHTML = result.outerHTML;
                }).catch(function (error) {
                    e.innerHTML = "graphviz render error: <br>".concat(error);
                    e.className = "vditor-reset--error";
                });
            }
            catch (e) {
                console.error("graphviz error", e);
            }
            e.setAttribute("data-processed", "true");
        });
    });
};


/***/ }),

/***/ 702:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "s": () => (/* binding */ highlightRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(998);
/* harmony import */ var _util_addStyle__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(296);



var highlightRender = function (hljsOption, element, cdn) {
    if (element === void 0) { element = document; }
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    var style = hljsOption.style;
    if (!_constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CODE_THEME.includes */ .g.CODE_THEME.includes(style)) {
        style = "github";
    }
    var vditorHljsStyle = document.getElementById("vditorHljsStyle");
    var href = "".concat(cdn, "/dist/js/highlight.js/styles/").concat(style, ".css");
    if (vditorHljsStyle && vditorHljsStyle.getAttribute('href') !== href) {
        vditorHljsStyle.remove();
    }
    (0,_util_addStyle__WEBPACK_IMPORTED_MODULE_1__/* .addStyle */ .c)("".concat(cdn, "/dist/js/highlight.js/styles/").concat(style, ".css"), "vditorHljsStyle");
    if (hljsOption.enable === false) {
        return;
    }
    var codes = element.querySelectorAll("pre > code");
    if (codes.length === 0) {
        return;
    }
    (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/highlight.js/highlight.pack.js"), "vditorHljsScript").then(function () {
        (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/highlight.js/solidity.min.js"), "vditorHljsSolidityScript").then(function () {
            (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/highlight.js/yul.min.js"), "vditorHljsYulScript").then(function () {
                element.querySelectorAll("pre > code").forEach(function (block) {
                    // ir & wysiwyg 区域不渲染
                    if (block.parentElement.classList.contains("vditor-ir__marker--pre") ||
                        block.parentElement.classList.contains("vditor-wysiwyg__pre")) {
                        return;
                    }
                    if (block.classList.contains("language-mermaid") || block.classList.contains("language-flowchart") ||
                        block.classList.contains("language-echarts") || block.classList.contains("language-mindmap") ||
                        block.classList.contains("language-plantuml") ||
                        block.classList.contains("language-abc") || block.classList.contains("language-graphviz") ||
                        block.classList.contains("language-math")) {
                        return;
                    }
                    if (hljsOption.defaultLang !== "" && block.className.indexOf("language-") === -1) {
                        block.classList.add("language-" + hljsOption.defaultLang);
                    }
                    hljs.highlightElement(block);
                    if (!hljsOption.lineNumber) {
                        return;
                    }
                    block.classList.add("vditor-linenumber");
                    var linenNumberTemp = block.querySelector(".vditor-linenumber__temp");
                    if (!linenNumberTemp) {
                        linenNumberTemp = document.createElement("div");
                        linenNumberTemp.className = "vditor-linenumber__temp";
                        block.insertAdjacentElement("beforeend", linenNumberTemp);
                    }
                    var whiteSpace = getComputedStyle(block).whiteSpace;
                    var isSoftWrap = false;
                    if (whiteSpace === "pre-wrap" || whiteSpace === "pre-line") {
                        isSoftWrap = true;
                    }
                    var lineNumberHTML = "";
                    var lineList = block.textContent.split(/\r\n|\r|\n/g);
                    lineList.pop();
                    lineList.map(function (line) {
                        var lineHeight = "";
                        if (isSoftWrap) {
                            linenNumberTemp.textContent = line || "\n";
                            lineHeight = " style=\"height:".concat(linenNumberTemp.getBoundingClientRect().height, "px\"");
                        }
                        lineNumberHTML += "<span".concat(lineHeight, "></span>");
                    });
                    linenNumberTemp.style.display = "none";
                    lineNumberHTML = "<span class=\"vditor-linenumber__rows\">".concat(lineNumberHTML, "</span>");
                    block.insertAdjacentHTML("beforeend", lineNumberHTML);
                });
            });
        });
    });
};


/***/ }),

/***/ 593:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "K": () => (/* binding */ markmapRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(998);
/* harmony import */ var _adapterRender__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(781);



var enabled = {};
var transform = function (transformer, content) {
    var result = transformer.transform(content);
    var keys = Object.keys(result.features).filter(function (key) { return !enabled[key]; });
    keys.forEach(function (key) {
        enabled[key] = true;
    });
    var _a = transformer.getAssets(keys), styles = _a.styles, scripts = _a.scripts;
    var markmap = window.markmap;
    if (styles)
        markmap.loadCSS(styles);
    if (scripts)
        markmap.loadJS(scripts);
    return result;
};
var init = function (el, code) {
    var _a = window.markmap, Transformer = _a.Transformer, Markmap = _a.Markmap, deriveOptions = _a.deriveOptions, globalCSS = _a.globalCSS;
    var transformer = new Transformer();
    el.innerHTML = '<svg style="width:100%"></svg>';
    var svg = el.firstChild;
    var mm = Markmap.create(svg, null);
    var _b = transform(transformer, code), root = _b.root, frontmatter = _b.frontmatter;
    var markmapOptions = frontmatter === null || frontmatter === void 0 ? void 0 : frontmatter.markmap;
    var frontmatterOptions = deriveOptions(markmapOptions);
    mm.setData(root, frontmatterOptions);
    mm.fit();
};
var markmapRender = function (element, cdn, theme) {
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    var markmapElements = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.markmapRenderAdapter.getElements(element);
    if (markmapElements.length === 0) {
        return;
    }
    (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/markmap/markmap.min.js"), "vditorMermaidScript").then(function () {
        markmapElements.forEach(function (item) {
            var code = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.markmapRenderAdapter.getCode(item);
            if (item.getAttribute("data-processed") === "true" || code.trim() === "") {
                return;
            }
            var render = document.createElement("div");
            render.className = "language-markmap";
            item.parentNode.appendChild(render);
            init(render, code);
            if (item.parentNode.childNodes[0].nodeName == "CODE") {
                item.parentNode.removeChild(item.parentNode.childNodes[0]);
            }
        });
    });
};


/***/ }),

/***/ 982:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "H": () => (/* binding */ mathRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(998);
/* harmony import */ var _util_addStyle__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(296);
/* harmony import */ var _util_code160to32__WEBPACK_IMPORTED_MODULE_4__ = __webpack_require__(528);
/* harmony import */ var _adapterRender__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(781);





var mathRender = function (element, options) {
    var mathElements = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.mathRenderAdapter.getElements(element);
    if (mathElements.length === 0) {
        return;
    }
    var defaultOptions = {
        cdn: _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN,
        math: {
            engine: "KaTeX",
            inlineDigit: false,
            macros: {},
        },
    };
    if (options && options.math) {
        options.math =
            Object.assign({}, defaultOptions.math, options.math);
    }
    options = Object.assign({}, defaultOptions, options);
    if (options.math.engine === "KaTeX") {
        (0,_util_addStyle__WEBPACK_IMPORTED_MODULE_2__/* .addStyle */ .c)("".concat(options.cdn, "/dist/js/katex/katex.min.css?v=0.16.9"), "vditorKatexStyle");
        (0,_util_addScript__WEBPACK_IMPORTED_MODULE_3__/* .addScript */ .G)("".concat(options.cdn, "/dist/js/katex/katex.min.js?v=0.16.9"), "vditorKatexScript").then(function () {
            (0,_util_addScript__WEBPACK_IMPORTED_MODULE_3__/* .addScript */ .G)("".concat(options.cdn, "/dist/js/katex/mhchem.min.js?v=0.16.9"), "vditorKatexChemScript").then(function () {
                mathElements.forEach(function (mathElement) {
                    if (mathElement.parentElement.classList.contains("vditor-wysiwyg__pre") ||
                        mathElement.parentElement.classList.contains("vditor-ir__marker--pre")) {
                        return;
                    }
                    if (mathElement.getAttribute("data-math")) {
                        return;
                    }
                    var math = (0,_util_code160to32__WEBPACK_IMPORTED_MODULE_4__/* .code160to32 */ .X)(_adapterRender__WEBPACK_IMPORTED_MODULE_1__.mathRenderAdapter.getCode(mathElement));
                    mathElement.setAttribute("data-math", math);
                    try {
                        mathElement.innerHTML = katex.renderToString(math, {
                            displayMode: mathElement.tagName === "DIV",
                            output: "html",
                            macros: options.math.macros,
                        });
                    }
                    catch (e) {
                        mathElement.innerHTML = e.message;
                        mathElement.className = "language-math vditor-reset--error";
                    }
                    mathElement.addEventListener("copy", function (event) {
                        event.stopPropagation();
                        event.preventDefault();
                        var vditorMathElement = event.currentTarget.closest(".language-math");
                        event.clipboardData.setData("text/html", vditorMathElement.innerHTML);
                        event.clipboardData.setData("text/plain", vditorMathElement.getAttribute("data-math"));
                    });
                });
            });
        });
    }
    else if (options.math.engine === "MathJax") {
        var chainAsync_1 = function (fns) {
            if (fns.length === 0) {
                return;
            }
            var curr = 0;
            var last = fns[fns.length - 1];
            var next = function () {
                var fn = fns[curr++];
                fn === last ? fn() : fn(next);
            };
            next();
        };
        if (!window.MathJax) {
            window.MathJax = {
                loader: {
                    paths: { mathjax: "".concat(options.cdn, "/dist/js/mathjax") },
                },
                startup: {
                    typeset: false,
                },
                tex: {
                    macros: options.math.macros,
                },
            };
            // https://github.com/Vanessa219/vditor/issues/1453
            Object.assign(window.MathJax, options.math.mathJaxOptions);
        }
        // 循环加载会抛异常
        (0,_util_addScript__WEBPACK_IMPORTED_MODULE_3__/* .addScriptSync */ .J)("".concat(options.cdn, "/dist/js/mathjax/tex-svg-full.js"), "protyleMathJaxScript");
        var renderMath_1 = function (mathElement, next) {
            var math = (0,_util_code160to32__WEBPACK_IMPORTED_MODULE_4__/* .code160to32 */ .X)(mathElement.textContent).trim();
            var mathOptions = window.MathJax.getMetricsFor(mathElement);
            mathOptions.display = mathElement.tagName === "DIV";
            window.MathJax.tex2svgPromise(math, mathOptions).then(function (node) {
                mathElement.innerHTML = "";
                mathElement.setAttribute("data-math", math);
                mathElement.append(node);
                window.MathJax.startup.document.clear();
                window.MathJax.startup.document.updateDocument();
                var errorTextElement = node.querySelector('[data-mml-node="merror"]');
                if (errorTextElement && errorTextElement.textContent.trim() !== "") {
                    mathElement.innerHTML = errorTextElement.textContent.trim();
                    mathElement.className = "vditor-reset--error";
                }
                if (next) {
                    next();
                }
            });
        };
        window.MathJax.startup.promise.then(function () {
            var chains = [];
            var _loop_1 = function (i) {
                var mathElement = mathElements[i];
                if (!mathElement.parentElement.classList.contains("vditor-wysiwyg__pre") &&
                    !mathElement.parentElement.classList.contains("vditor-ir__marker--pre") &&
                    !mathElement.getAttribute("data-math") && (0,_util_code160to32__WEBPACK_IMPORTED_MODULE_4__/* .code160to32 */ .X)(mathElement.textContent).trim()) {
                    chains.push(function (next) {
                        if (i === mathElements.length - 1) {
                            renderMath_1(mathElement);
                        }
                        else {
                            renderMath_1(mathElement, next);
                        }
                    });
                }
            };
            for (var i = 0; i < mathElements.length; i++) {
                _loop_1(i);
            }
            chainAsync_1(chains);
        });
    }
};


/***/ }),

/***/ 431:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "Y": () => (/* binding */ mediaRender)
/* harmony export */ });
/* harmony import */ var _util_function__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(446);

var videoRender = function (element, url) {
    element.insertAdjacentHTML("afterend", "<video controls=\"controls\" src=\"".concat(url, "\"></video>"));
    element.remove();
};
var audioRender = function (element, url) {
    element.insertAdjacentHTML("afterend", "<audio controls=\"controls\" src=\"".concat(url, "\"></audio>"));
    element.remove();
};
var iframeRender = function (element, url) {
    var youtubeMatch = url.match(/\/\/(?:www\.)?(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([\w|-]{11})(?:(?:[\?&]t=)(\S+))?/);
    var youkuMatch = url.match(/\/\/v\.youku\.com\/v_show\/id_(\w+)=*\.html/);
    var qqMatch = url.match(/\/\/v\.qq\.com\/x\/cover\/.*\/([^\/]+)\.html\??.*/);
    var coubMatch = url.match(/(?:www\.|\/\/)coub\.com\/view\/(\w+)/);
    var facebookMatch = url.match(/(?:www\.|\/\/)facebook\.com\/([^\/]+)\/videos\/([0-9]+)/);
    var dailymotionMatch = url.match(/.+dailymotion.com\/(video|hub)\/(\w+)\?/);
    var bilibiliMatch = url.match(/(?:www\.|\/\/)bilibili\.com\/video\/(\w+)/);
    var tedMatch = url.match(/(?:www\.|\/\/)ted\.com\/talks\/(\w+)/);
    if (youtubeMatch && youtubeMatch[1].length === 11) {
        element.insertAdjacentHTML("afterend", "<iframe class=\"iframe__video\" src=\"//www.youtube.com/embed/".concat(youtubeMatch[1] +
            (youtubeMatch[2] ? "?start=" + youtubeMatch[2] : ""), "\"></iframe>"));
        element.remove();
    }
    else if (youkuMatch && youkuMatch[1]) {
        element.insertAdjacentHTML("afterend", "<iframe class=\"iframe__video\" src=\"//player.youku.com/embed/".concat(youkuMatch[1], "\"></iframe>"));
        element.remove();
    }
    else if (qqMatch && qqMatch[1]) {
        element.insertAdjacentHTML("afterend", "<iframe class=\"iframe__video\" src=\"https://v.qq.com/txp/iframe/player.html?vid=".concat(qqMatch[1], "\"></iframe>"));
        element.remove();
    }
    else if (coubMatch && coubMatch[1]) {
        element.insertAdjacentHTML("afterend", "<iframe class=\"iframe__video\"\n src=\"//coub.com/embed/".concat(coubMatch[1], "?muted=false&autostart=false&originalSize=true&startWithHD=true\"></iframe>"));
        element.remove();
    }
    else if (facebookMatch && facebookMatch[0]) {
        element.insertAdjacentHTML("afterend", "<iframe class=\"iframe__video\"\n src=\"https://www.facebook.com/plugins/video.php?href=".concat(encodeURIComponent(facebookMatch[0]), "\"></iframe>"));
        element.remove();
    }
    else if (dailymotionMatch && dailymotionMatch[2]) {
        element.insertAdjacentHTML("afterend", "<iframe class=\"iframe__video\"\n src=\"https://www.dailymotion.com/embed/video/".concat(dailymotionMatch[2], "\"></iframe>"));
        element.remove();
    }
    else if (url.indexOf("bilibili.com") > -1 && (url.indexOf("bvid=") > -1 || (bilibiliMatch && bilibiliMatch[1]))) {
        var params_1 = {
            bvid: (0,_util_function__WEBPACK_IMPORTED_MODULE_0__/* .getSearch */ .o)("bvid", url) || (bilibiliMatch && bilibiliMatch[1]),
            page: "1",
            high_quality: "1",
            as_wide: "1",
            allowfullscreen: "true",
            autoplay: "0"
        };
        new URL(url.startsWith("http") ? url : "https:" + url).search.split("&").forEach(function (item, index) {
            if (!item) {
                return;
            }
            if (index === 0) {
                item = item.substr(1);
            }
            var keyValue = item.split("=");
            params_1[keyValue[0]] = keyValue[1];
        });
        var src_1 = "https://player.bilibili.com/player.html?";
        var keys_1 = Object.keys(params_1);
        keys_1.forEach(function (key, index) {
            src_1 += "".concat(key, "=").concat(params_1[key]);
            if (index < keys_1.length - 1) {
                src_1 += "&";
            }
        });
        element.insertAdjacentHTML("afterend", "<iframe class=\"iframe__video\" src=\"".concat(src_1, "\"></iframe>"));
        element.remove();
    }
    else if (tedMatch && tedMatch[1]) {
        element.insertAdjacentHTML("afterend", "<iframe class=\"iframe__video\" src=\"//embed.ted.com/talks/".concat(tedMatch[1], "\"></iframe>"));
        element.remove();
    }
};
var mediaRender = function (element) {
    if (!element) {
        return;
    }
    element.querySelectorAll("a").forEach(function (aElement) {
        var url = aElement.getAttribute("href");
        if (!url) {
            return;
        }
        if (url.match(/^.+.(mp4|m4v|ogg|ogv|webm)$/)) {
            videoRender(aElement, url);
        }
        else if (url.match(/^.+.(mp3|wav|flac)$/)) {
            audioRender(aElement, url);
        }
        else {
            iframeRender(aElement, url);
        }
    });
};


/***/ }),

/***/ 570:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "i": () => (/* binding */ mermaidRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(998);
/* harmony import */ var _adapterRender__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(781);
/* harmony import */ var _util_function__WEBPACK_IMPORTED_MODULE_3__ = __webpack_require__(446);
var __awaiter = (undefined && undefined.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (undefined && undefined.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g;
    return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};




var mermaidRender = function (element, cdn, theme) {
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    var mermaidElements = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.mermaidRenderAdapter.getElements(element);
    if (mermaidElements.length === 0) {
        return;
    }
    (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/mermaid/mermaid.min.js"), "vditorMermaidScript").then(function () {
        var config = {
            securityLevel: "loose",
            altFontFamily: "sans-serif",
            fontFamily: "sans-serif",
            startOnLoad: false,
            flowchart: {
                htmlLabels: true,
                useMaxWidth: !0
            },
            sequence: {
                useMaxWidth: true,
                diagramMarginX: 8,
                diagramMarginY: 8,
                boxMargin: 8,
                showSequenceNumbers: true // Mermaid 时序图增加序号 https://github.com/siyuan-note/siyuan/pull/6992 https://mermaid.js.org/syntax/sequenceDiagram.html#sequencenumbers
            },
            gantt: {
                leftPadding: 75,
                rightPadding: 20
            }
        };
        if (theme === "dark") {
            config.theme = "dark";
        }
        mermaid.initialize(config);
        mermaidElements.forEach(function (item) { return __awaiter(void 0, void 0, void 0, function () {
            var code, id, mermaidData, e_1, errorElement;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        code = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.mermaidRenderAdapter.getCode(item);
                        if (item.getAttribute("data-processed") === "true" || code.trim() === "") {
                            return [2 /*return*/];
                        }
                        id = "mermaid" + (0,_util_function__WEBPACK_IMPORTED_MODULE_3__/* .genUUID */ .W)();
                        _a.label = 1;
                    case 1:
                        _a.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, mermaid.render(id, item.textContent)];
                    case 2:
                        mermaidData = _a.sent();
                        item.innerHTML = mermaidData.svg;
                        return [3 /*break*/, 4];
                    case 3:
                        e_1 = _a.sent();
                        errorElement = document.querySelector("#" + id);
                        item.innerHTML = "".concat(errorElement.outerHTML, "<br>\n<div style=\"text-align: left\"><small>").concat(e_1.message.replace(/\n/, "<br>"), "</small></div>");
                        errorElement.parentElement.remove();
                        return [3 /*break*/, 4];
                    case 4:
                        item.setAttribute("data-processed", "true");
                        return [2 /*return*/];
                }
            });
        }); });
    });
};


/***/ }),

/***/ 558:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "P": () => (/* binding */ mindmapRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(998);
/* harmony import */ var _adapterRender__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(781);



var mindmapRender = function (element, cdn, theme) {
    if (element === void 0) { element = document; }
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    var mindmapElements = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.mindmapRenderAdapter.getElements(element);
    if (mindmapElements.length > 0) {
        (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/echarts/echarts.min.js"), "vditorEchartsScript").then(function () {
            mindmapElements.forEach(function (e) {
                if (e.parentElement.classList.contains("vditor-wysiwyg__pre") ||
                    e.parentElement.classList.contains("vditor-ir__marker--pre")) {
                    return;
                }
                var text = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.mindmapRenderAdapter.getCode(e);
                if (!text) {
                    return;
                }
                try {
                    if (e.getAttribute("data-processed") === "true") {
                        return;
                    }
                    echarts.init(e, theme === "dark" ? "dark" : undefined).setOption({
                        series: [
                            {
                                data: [JSON.parse(decodeURIComponent(text))],
                                initialTreeDepth: -1,
                                itemStyle: {
                                    borderWidth: 0,
                                    color: "#4285f4",
                                },
                                label: {
                                    backgroundColor: "#f6f8fa",
                                    borderColor: "#d1d5da",
                                    borderRadius: 5,
                                    borderWidth: 0.5,
                                    color: "#586069",
                                    lineHeight: 20,
                                    offset: [-5, 0],
                                    padding: [0, 5],
                                    position: "insideRight",
                                },
                                lineStyle: {
                                    color: "#d1d5da",
                                    width: 1,
                                },
                                roam: true,
                                symbol: function (value, params) {
                                    var _a;
                                    if ((_a = params === null || params === void 0 ? void 0 : params.data) === null || _a === void 0 ? void 0 : _a.children) {
                                        return "circle";
                                    }
                                    else {
                                        return "path://";
                                    }
                                },
                                type: "tree",
                            },
                        ],
                        tooltip: {
                            trigger: "item",
                            triggerOn: "mousemove",
                        },
                    });
                    e.setAttribute("data-processed", "true");
                }
                catch (error) {
                    e.className = "vditor-reset--error";
                    e.innerHTML = "mindmap render error: <br>".concat(error);
                }
            });
        });
    }
};


/***/ }),

/***/ 182:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "k": () => (/* binding */ outlineRender)
/* harmony export */ });
/* harmony import */ var _util_hasClosestByHeadings__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(946);
/* harmony import */ var _mathRender__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(982);


var outlineRender = function (contentElement, targetElement, vditor) {
    var tocHTML = "";
    var ids = [];
    Array.from(contentElement.children).forEach(function (item, index) {
        if ((0,_util_hasClosestByHeadings__WEBPACK_IMPORTED_MODULE_1__/* .hasClosestByHeadings */ .W)(item)) {
            if (vditor) {
                var lastIndex = item.id.lastIndexOf("_");
                item.id = item.id.substring(0, lastIndex === -1 ? undefined : lastIndex) + "_" + index;
            }
            ids.push(item.id);
            tocHTML += item.outerHTML.replace("<wbr>", "");
        }
    });
    if (tocHTML === "") {
        targetElement.innerHTML = "";
        return "";
    }
    var tempElement = document.createElement("div");
    if (vditor) {
        vditor.lute.SetToC(true);
        if (vditor.currentMode === "wysiwyg" && !vditor.preview.element.contains(contentElement)) {
            tempElement.innerHTML = vditor.lute.SpinVditorDOM("<p>[ToC]</p>" + tocHTML);
        }
        else if (vditor.currentMode === "ir" && !vditor.preview.element.contains(contentElement)) {
            tempElement.innerHTML = vditor.lute.SpinVditorIRDOM("<p>[ToC]</p>" + tocHTML);
        }
        else {
            tempElement.innerHTML = vditor.lute.HTML2VditorDOM("<p>[ToC]</p>" + tocHTML);
        }
        vditor.lute.SetToC(vditor.options.preview.markdown.toc);
    }
    else {
        targetElement.classList.add("vditor-outline");
        var lute = Lute.New();
        lute.SetToC(true);
        tempElement.innerHTML = lute.HTML2VditorDOM("<p>[ToC]</p>" + tocHTML);
    }
    var headingsElement = tempElement.firstElementChild.querySelectorAll("li > span[data-target-id]");
    headingsElement.forEach(function (item, index) {
        if (item.nextElementSibling && item.nextElementSibling.tagName === "UL") {
            var iconHTML = "<svg class='vditor-outline__action'><use xlink:href='#vditor-icon-down'></use></svg>";
            if (!document.getElementById("vditorIconScript")) {
                iconHTML = '<svg class="vditor-outline__action" viewBox="0 0 32 32"><path d="M3.76 6.12l12.24 12.213 12.24-12.213 3.76 3.76-16 16-16-16 3.76-3.76z"></path></svg>';
            }
            item.innerHTML = "".concat(iconHTML, "<span>").concat(item.innerHTML, "</span>");
        }
        else {
            item.innerHTML = "<svg></svg><span>".concat(item.innerHTML, "</span>");
        }
        item.setAttribute("data-target-id", ids[index]);
    });
    tocHTML = tempElement.firstElementChild.innerHTML;
    if (headingsElement.length === 0) {
        targetElement.innerHTML = "";
        return tocHTML;
    }
    targetElement.innerHTML = tocHTML;
    if (vditor) {
        (0,_mathRender__WEBPACK_IMPORTED_MODULE_0__/* .mathRender */ .H)(targetElement, {
            cdn: vditor.options.cdn,
            math: vditor.options.preview.math,
        });
    }
    targetElement.firstElementChild.addEventListener("click", function (event) {
        var target = event.target;
        while (target && !target.isEqualNode(targetElement)) {
            if (target.classList.contains("vditor-outline__action")) {
                if (target.classList.contains("vditor-outline__action--close")) {
                    target.classList.remove("vditor-outline__action--close");
                    target.parentElement.nextElementSibling.setAttribute("style", "display:block");
                }
                else {
                    target.classList.add("vditor-outline__action--close");
                    target.parentElement.nextElementSibling.setAttribute("style", "display:none");
                }
                event.preventDefault();
                event.stopPropagation();
                break;
            }
            else if (target.getAttribute("data-target-id")) {
                event.preventDefault();
                event.stopPropagation();
                var idElement = document.getElementById(target.getAttribute("data-target-id"));
                if (!idElement) {
                    return;
                }
                if (vditor) {
                    if (vditor.options.height === "auto") {
                        var windowScrollY = idElement.offsetTop + vditor.element.offsetTop;
                        if (!vditor.options.toolbarConfig.pin) {
                            windowScrollY += vditor.toolbar.element.offsetHeight;
                        }
                        window.scrollTo(window.scrollX, windowScrollY);
                    }
                    else {
                        if (vditor.element.offsetTop < window.scrollY) {
                            window.scrollTo(window.scrollX, vditor.element.offsetTop);
                        }
                        if (vditor.preview.element.contains(contentElement)) {
                            contentElement.parentElement.scrollTop = idElement.offsetTop;
                        }
                        else {
                            contentElement.scrollTop = idElement.offsetTop;
                        }
                    }
                }
                else {
                    window.scrollTo(window.scrollX, idElement.offsetTop);
                }
                break;
            }
            target = target.parentElement;
        }
    });
    return tocHTML;
};


/***/ }),

/***/ 931:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "B": () => (/* binding */ plantumlRender)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addScript__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(998);
/* harmony import */ var _adapterRender__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(781);



var plantumlRender = function (element, cdn) {
    if (element === void 0) { element = document; }
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    var plantumlElements = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.plantumlRenderAdapter.getElements(element);
    if (plantumlElements.length === 0) {
        return;
    }
    (0,_util_addScript__WEBPACK_IMPORTED_MODULE_2__/* .addScript */ .G)("".concat(cdn, "/dist/js/plantuml/plantuml-encoder.min.js"), "vditorPlantumlScript").then(function () {
        plantumlElements.forEach(function (e) {
            if (e.parentElement.classList.contains("vditor-wysiwyg__pre") ||
                e.parentElement.classList.contains("vditor-ir__marker--pre")) {
                return;
            }
            var text = _adapterRender__WEBPACK_IMPORTED_MODULE_1__.plantumlRenderAdapter.getCode(e).trim();
            if (!text) {
                return;
            }
            try {
                e.innerHTML = "<object type=\"image/svg+xml\" data=\"https://www.plantuml.com/plantuml/svg/~1".concat(plantumlEncoder.encode(text), "\"/>");
            }
            catch (error) {
                e.className = "vditor-reset--error";
                e.innerHTML = "plantuml render error: <br>".concat(error);
            }
        });
    });
};


/***/ }),

/***/ 65:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "X": () => (/* binding */ setLute)
/* harmony export */ });
var setLute = function (options) {
    var lute = Lute.New();
    lute.PutEmojis(options.emojis);
    lute.SetEmojiSite(options.emojiSite);
    lute.SetHeadingAnchor(options.headingAnchor);
    lute.SetInlineMathAllowDigitAfterOpenMarker(options.inlineMathDigit);
    lute.SetAutoSpace(options.autoSpace);
    lute.SetToC(options.toc);
    lute.SetFootnotes(options.footnotes);
    lute.SetFixTermTypo(options.fixTermTypo);
    lute.SetVditorCodeBlockPreview(options.codeBlockPreview);
    lute.SetVditorMathBlockPreview(options.mathBlockPreview);
    lute.SetSanitize(options.sanitize);
    lute.SetChineseParagraphBeginningSpace(options.paragraphBeginningSpace);
    lute.SetRenderListStyle(options.listStyle);
    lute.SetLinkBase(options.linkBase);
    lute.SetLinkPrefix(options.linkPrefix);
    lute.SetMark(options.mark);
    lute.SetGFMAutoLink(options.gfmAutoLink);
    if (options.lazyLoadImage) {
        lute.SetImageLazyLoading(options.lazyLoadImage);
    }
    return lute;
};


/***/ }),

/***/ 971:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "E": () => (/* binding */ previewImage)
/* harmony export */ });
var previewImage = function (oldImgElement, lang, theme) {
    if (lang === void 0) { lang = "zh_CN"; }
    if (theme === void 0) { theme = "classic"; }
    var oldImgRect = oldImgElement.getBoundingClientRect();
    var height = 36;
    document.body.insertAdjacentHTML("beforeend", "<div class=\"vditor vditor-img".concat(theme === "dark" ? " vditor--dark" : "", "\">\n    <div class=\"vditor-img__bar\">\n      <span class=\"vditor-img__btn\" data-deg=\"0\">\n        <svg><use xlink:href=\"#vditor-icon-redo\"></use></svg>\n        ").concat(window.VditorI18n.spin, "\n      </span>\n      <span class=\"vditor-img__btn\"  onclick=\"this.parentElement.parentElement.outerHTML = '';document.body.style.overflow = ''\">\n        X &nbsp;").concat(window.VditorI18n.close, "\n      </span>\n    </div>\n    <div class=\"vditor-img__img\" onclick=\"this.parentElement.outerHTML = '';document.body.style.overflow = ''\">\n      <img style=\"width: ").concat(oldImgElement.width, "px;height:").concat(oldImgElement.height, "px;transform: translate3d(").concat(oldImgRect.left, "px, ").concat(oldImgRect.top - height, "px, 0)\" src=\"").concat(oldImgElement.getAttribute("src"), "\">\n    </div>\n</div>"));
    document.body.style.overflow = "hidden";
    // 图片从原始位置移动到预览正中间的动画效果
    var imgElement = document.querySelector(".vditor-img img");
    var translate3d = "translate3d(".concat(Math.max(0, window.innerWidth - oldImgElement.naturalWidth) / 2, "px, ").concat(Math.max(0, window.innerHeight - height - oldImgElement.naturalHeight) / 2, "px, 0)");
    setTimeout(function () {
        imgElement.setAttribute("style", "transition: transform .3s ease-in-out;transform: ".concat(translate3d));
        setTimeout(function () {
            imgElement.parentElement.scrollTo((imgElement.parentElement.scrollWidth - imgElement.parentElement.clientWidth) / 2, (imgElement.parentElement.scrollHeight - imgElement.parentElement.clientHeight) / 2);
        }, 400);
    });
    // 旋转
    var btnElement = document.querySelector(".vditor-img__btn");
    btnElement.addEventListener("click", function () {
        var deg = parseInt(btnElement.getAttribute("data-deg"), 10) + 90;
        if ((deg / 90) % 2 === 1 && oldImgElement.naturalWidth > imgElement.parentElement.clientHeight) {
            imgElement.style.transform = "translate3d(".concat(Math.max(0, window.innerWidth - oldImgElement.naturalWidth) / 2, "px, ").concat(oldImgElement.naturalWidth / 2 - oldImgElement.naturalHeight / 2, "px, 0) rotateZ(").concat(deg, "deg)");
        }
        else {
            imgElement.style.transform = "".concat(translate3d, " rotateZ(").concat(deg, "deg)");
        }
        btnElement.setAttribute("data-deg", deg.toString());
        setTimeout(function () {
            imgElement.parentElement.scrollTo((imgElement.parentElement.scrollWidth - imgElement.parentElement.clientWidth) / 2, (imgElement.parentElement.scrollHeight - imgElement.parentElement.clientHeight) / 2);
        }, 400);
    });
};


/***/ }),

/***/ 34:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "Y": () => (/* binding */ setCodeTheme)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _util_addStyle__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(296);


var setCodeTheme = function (codeTheme, cdn) {
    if (cdn === void 0) { cdn = _constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CDN */ .g.CDN; }
    if (!_constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.CODE_THEME.includes */ .g.CODE_THEME.includes(codeTheme)) {
        codeTheme = "github";
    }
    var vditorHljsStyle = document.getElementById("vditorHljsStyle");
    var href = "".concat(cdn, "/dist/js/highlight.js/styles/").concat(codeTheme, ".css");
    if (!vditorHljsStyle) {
        (0,_util_addStyle__WEBPACK_IMPORTED_MODULE_1__/* .addStyle */ .c)(href, "vditorHljsStyle");
    }
    else if (vditorHljsStyle.getAttribute('href') !== href) {
        vditorHljsStyle.remove();
        (0,_util_addStyle__WEBPACK_IMPORTED_MODULE_1__/* .addStyle */ .c)(href, "vditorHljsStyle");
    }
};


/***/ }),

/***/ 652:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "Z": () => (/* binding */ setContentTheme)
/* harmony export */ });
/* harmony import */ var _util_addStyle__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(296);

var setContentTheme = function (contentTheme, path) {
    if (!contentTheme || !path) {
        return;
    }
    var vditorContentTheme = document.getElementById("vditorContentTheme");
    var cssPath = "".concat(path, "/").concat(contentTheme, ".css");
    if (!vditorContentTheme) {
        (0,_util_addStyle__WEBPACK_IMPORTED_MODULE_0__/* .addStyle */ .c)(cssPath, "vditorContentTheme");
    }
    else if (vditorContentTheme.getAttribute("href") !== cssPath) {
        vditorContentTheme.remove();
        (0,_util_addStyle__WEBPACK_IMPORTED_MODULE_0__/* .addStyle */ .c)(cssPath, "vditorContentTheme");
    }
};


/***/ }),

/***/ 998:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "G": () => (/* binding */ addScript),
/* harmony export */   "J": () => (/* binding */ addScriptSync)
/* harmony export */ });
var addScriptSync = function (path, id) {
    if (document.getElementById(id)) {
        return false;
    }
    var xhrObj = new XMLHttpRequest();
    xhrObj.open("GET", path, false);
    xhrObj.setRequestHeader("Accept", "text/javascript, application/javascript, application/ecmascript, application/x-ecmascript, */*; q=0.01");
    xhrObj.send("");
    var scriptElement = document.createElement("script");
    scriptElement.type = "text/javascript";
    scriptElement.text = xhrObj.responseText;
    scriptElement.id = id;
    document.head.appendChild(scriptElement);
};
var addScript = function (path, id) {
    return new Promise(function (resolve, reject) {
        if (document.getElementById(id)) {
            // 脚本加载后再次调用直接返回
            resolve(true);
            return false;
        }
        var scriptElement = document.createElement("script");
        scriptElement.src = path;
        scriptElement.async = true;
        // 循环调用时 Chrome 不会重复请求 js
        document.head.appendChild(scriptElement);
        scriptElement.onerror = function (event) {
            reject(event);
        };
        scriptElement.onload = function () {
            if (document.getElementById(id)) {
                // 循环调用需清除 DOM 中的 script 标签
                scriptElement.remove();
                resolve(true);
                return false;
            }
            scriptElement.id = id;
            resolve(true);
        };
    });
};


/***/ }),

/***/ 296:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "c": () => (/* binding */ addStyle)
/* harmony export */ });
var addStyle = function (url, id) {
    if (!document.getElementById(id)) {
        var styleElement = document.createElement("link");
        styleElement.id = id;
        styleElement.rel = "stylesheet";
        styleElement.type = "text/css";
        styleElement.href = url;
        document.getElementsByTagName("head")[0].appendChild(styleElement);
    }
};


/***/ }),

/***/ 528:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "X": () => (/* binding */ code160to32)
/* harmony export */ });
var code160to32 = function (text) {
    // 非打断空格转换为空格
    return text.replace(/\u00a0/g, " ");
};


/***/ }),

/***/ 796:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "G6": () => (/* binding */ isSafari),
/* harmony export */   "Le": () => (/* binding */ getEventName),
/* harmony export */   "i7": () => (/* binding */ isChrome),
/* harmony export */   "ns": () => (/* binding */ updateHotkeyTip),
/* harmony export */   "pK": () => (/* binding */ accessLocalStorage),
/* harmony export */   "vU": () => (/* binding */ isFirefox),
/* harmony export */   "yl": () => (/* binding */ isCtrl)
/* harmony export */ });
var isSafari = function () {
    return navigator.userAgent.indexOf("Safari") > -1 && navigator.userAgent.indexOf("Chrome") === -1;
};
var isFirefox = function () {
    return navigator.userAgent.toLowerCase().indexOf("firefox") > -1;
};
var accessLocalStorage = function () {
    try {
        return typeof localStorage !== "undefined";
    }
    catch (e) {
        return false;
    }
};
// 用户 iPhone 点击延迟/需要双击的处理
var getEventName = function () {
    if (navigator.userAgent.indexOf("iPhone") > -1) {
        return "touchstart";
    }
    else {
        return "click";
    }
};
// 区别 mac 上的 ctrl 和 meta
var isCtrl = function (event) {
    if (navigator.platform.toUpperCase().indexOf("MAC") >= 0) {
        // mac
        if (event.metaKey && !event.ctrlKey) {
            return true;
        }
        return false;
    }
    else {
        if (!event.metaKey && event.ctrlKey) {
            return true;
        }
        return false;
    }
};
// Mac，Windows 快捷键展示
var updateHotkeyTip = function (hotkey) {
    if (/Mac/.test(navigator.platform) || navigator.platform === "iPhone") {
        if (hotkey.indexOf("⇧") > -1 && isFirefox()) {
            // Mac Firefox 按下 shift 后，key 同 windows 系统
            hotkey = hotkey.replace(";", ":").replace("=", "+").replace("-", "_");
        }
    }
    else {
        if (hotkey.startsWith("⌘")) {
            hotkey = hotkey.replace("⌘", "⌘+");
        }
        else if (hotkey.startsWith("⌥") && hotkey.substr(1, 1) !== "⌘") {
            hotkey = hotkey.replace("⌥", "⌥+");
        }
        else {
            hotkey = hotkey.replace("⇧⌘", "⌘+⇧+").replace("⌥⌘", "⌥+⌘+");
        }
        hotkey = hotkey.replace("⌘", "Ctrl").replace("⇧", "Shift")
            .replace("⌥", "Alt");
        if (hotkey.indexOf("Shift") > -1) {
            hotkey = hotkey.replace(";", ":").replace("=", "+").replace("-", "_");
        }
    }
    return hotkey;
};
var isChrome = function () {
    return /Chrome/.test(navigator.userAgent) && /Google Inc/.test(navigator.vendor);
};


/***/ }),

/***/ 446:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "W": () => (/* binding */ genUUID),
/* harmony export */   "o": () => (/* binding */ getSearch)
/* harmony export */ });
var genUUID = function () { return ([1e7].toString() + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, function (c) {
    return (parseInt(c, 10) ^ (window.crypto.getRandomValues(new Uint32Array(1))[0] & (15 >> (parseInt(c, 10) / 4)))).toString(16);
}); };
var getSearch = function (key, link) {
    if (link === void 0) { link = window.location.search; }
    var params = link.substring(link.indexOf("?"));
    var hashIndex = params.indexOf("#");
    // REF https://developer.mozilla.org/zh-CN/docs/Web/API/URLSearchParams
    var urlSearchParams = new URLSearchParams(params.substring(0, hashIndex >= 0 ? hashIndex : undefined));
    return urlSearchParams.get(key);
};


/***/ }),

/***/ 118:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "DX": () => (/* binding */ getLastNode),
/* harmony export */   "E2": () => (/* binding */ hasTopClosestByTag),
/* harmony export */   "F9": () => (/* binding */ hasClosestBlock),
/* harmony export */   "JQ": () => (/* binding */ hasTopClosestByClassName),
/* harmony export */   "O9": () => (/* binding */ getTopList),
/* harmony export */   "a1": () => (/* binding */ hasClosestByAttribute),
/* harmony export */   "fb": () => (/* binding */ hasClosestByClassName),
/* harmony export */   "lG": () => (/* binding */ hasClosestByMatchTag)
/* harmony export */ });
/* unused harmony export hasTopClosestByAttribute */
/* harmony import */ var _hasClosestByHeadings__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(946);

var hasTopClosestByClassName = function (element, className) {
    var closest = hasClosestByClassName(element, className);
    var parentClosest = false;
    var findTop = false;
    while (closest && !closest.classList.contains("vditor-reset") && !findTop) {
        parentClosest = hasClosestByClassName(closest.parentElement, className);
        if (parentClosest) {
            closest = parentClosest;
        }
        else {
            findTop = true;
        }
    }
    return closest || false;
};
var hasTopClosestByAttribute = function (element, attr, value) {
    var closest = hasClosestByAttribute(element, attr, value);
    var parentClosest = false;
    var findTop = false;
    while (closest && !closest.classList.contains("vditor-reset") && !findTop) {
        parentClosest = hasClosestByAttribute(closest.parentElement, attr, value);
        if (parentClosest) {
            closest = parentClosest;
        }
        else {
            findTop = true;
        }
    }
    return closest || false;
};
var hasTopClosestByTag = function (element, nodeName) {
    var closest = (0,_hasClosestByHeadings__WEBPACK_IMPORTED_MODULE_0__/* .hasClosestByTag */ .S)(element, nodeName);
    var parentClosest = false;
    var findTop = false;
    while (closest && !closest.classList.contains("vditor-reset") && !findTop) {
        parentClosest = (0,_hasClosestByHeadings__WEBPACK_IMPORTED_MODULE_0__/* .hasClosestByTag */ .S)(closest.parentElement, nodeName);
        if (parentClosest) {
            closest = parentClosest;
        }
        else {
            findTop = true;
        }
    }
    return closest || false;
};
var getTopList = function (element) {
    var topUlElement = hasTopClosestByTag(element, "UL");
    var topOlElement = hasTopClosestByTag(element, "OL");
    var topListElement = topUlElement;
    if (topOlElement && (!topUlElement || (topUlElement && topOlElement.contains(topUlElement)))) {
        topListElement = topOlElement;
    }
    return topListElement;
};
var hasClosestByAttribute = function (element, attr, value) {
    if (!element) {
        return false;
    }
    if (element.nodeType === 3) {
        element = element.parentElement;
    }
    var e = element;
    var isClosest = false;
    while (e && !isClosest && !e.classList.contains("vditor-reset")) {
        if (e.getAttribute(attr) === value) {
            isClosest = true;
        }
        else {
            e = e.parentElement;
        }
    }
    return isClosest && e;
};
var hasClosestBlock = function (element) {
    if (!element) {
        return false;
    }
    if (element.nodeType === 3) {
        element = element.parentElement;
    }
    var e = element;
    var isClosest = false;
    var blockElement = hasClosestByAttribute(element, "data-block", "0");
    if (blockElement) {
        return blockElement;
    }
    while (e && !isClosest && !e.classList.contains("vditor-reset")) {
        if (e.tagName === "H1" ||
            e.tagName === "H2" ||
            e.tagName === "H3" ||
            e.tagName === "H4" ||
            e.tagName === "H5" ||
            e.tagName === "H6" ||
            e.tagName === "P" ||
            e.tagName === "BLOCKQUOTE" ||
            e.tagName === "OL" ||
            e.tagName === "UL") {
            isClosest = true;
        }
        else {
            e = e.parentElement;
        }
    }
    return isClosest && e;
};
var hasClosestByMatchTag = function (element, nodeName) {
    if (!element) {
        return false;
    }
    if (element.nodeType === 3) {
        element = element.parentElement;
    }
    var e = element;
    var isClosest = false;
    while (e && !isClosest && !e.classList.contains("vditor-reset")) {
        if (e.nodeName === nodeName) {
            isClosest = true;
        }
        else {
            e = e.parentElement;
        }
    }
    return isClosest && e;
};
var hasClosestByClassName = function (element, className) {
    if (!element) {
        return false;
    }
    if (element.nodeType === 3) {
        element = element.parentElement;
    }
    var e = element;
    var isClosest = false;
    while (e && !isClosest && !e.classList.contains("vditor-reset")) {
        if (e.classList.contains(className)) {
            isClosest = true;
        }
        else {
            e = e.parentElement;
        }
    }
    return isClosest && e;
};
var getLastNode = function (node) {
    while (node && node.lastChild) {
        node = node.lastChild;
    }
    return node;
};


/***/ }),

/***/ 946:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "S": () => (/* binding */ hasClosestByTag),
/* harmony export */   "W": () => (/* binding */ hasClosestByHeadings)
/* harmony export */ });
// NOTE: 减少 method.ts 打包，故从 hasClosest.ts 中拆分
var hasClosestByTag = function (element, nodeName) {
    if (!element) {
        return false;
    }
    if (element.nodeType === 3) {
        element = element.parentElement;
    }
    var e = element;
    var isClosest = false;
    while (e && !isClosest && !e.classList.contains("vditor-reset")) {
        if (e.nodeName.indexOf(nodeName) === 0) {
            isClosest = true;
        }
        else {
            e = e.parentElement;
        }
    }
    return isClosest && e;
};
var hasClosestByHeadings = function (element) {
    var headingElement = hasClosestByTag(element, "H");
    if (headingElement && headingElement.tagName.length === 2 && headingElement.tagName !== "HR") {
        return headingElement;
    }
    return false;
};


/***/ }),

/***/ 2:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "T": () => (/* binding */ merge)
/* harmony export */ });
var merge = function () {
    var options = [];
    for (var _i = 0; _i < arguments.length; _i++) {
        options[_i] = arguments[_i];
    }
    var target = {};
    var merger = function (obj) {
        for (var prop in obj) {
            if (obj.hasOwnProperty(prop)) {
                if (Object.prototype.toString.call(obj[prop]) === "[object Object]") {
                    target[prop] = merge(target[prop], obj[prop]);
                }
                else {
                    target[prop] = obj[prop];
                }
            }
        }
    };
    for (var i = 0; i < options.length; i++) {
        merger(options[i]);
    }
    return target;
};


/***/ }),

/***/ 307:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

"use strict";
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "$j": () => (/* binding */ setSelectionByPosition),
/* harmony export */   "Gb": () => (/* binding */ selectIsEditor),
/* harmony export */   "Hc": () => (/* binding */ setSelectionFocus),
/* harmony export */   "Ny": () => (/* binding */ getCursorPosition),
/* harmony export */   "ib": () => (/* binding */ setRangeByWbr),
/* harmony export */   "im": () => (/* binding */ getSelectPosition),
/* harmony export */   "oC": () => (/* binding */ insertHTML),
/* harmony export */   "zh": () => (/* binding */ getEditorRange)
/* harmony export */ });
/* harmony import */ var _constants__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(793);
/* harmony import */ var _compatibility__WEBPACK_IMPORTED_MODULE_2__ = __webpack_require__(796);
/* harmony import */ var _hasClosest__WEBPACK_IMPORTED_MODULE_1__ = __webpack_require__(118);



var getEditorRange = function (vditor) {
    var range;
    var element = vditor[vditor.currentMode].element;
    if (getSelection().rangeCount > 0) {
        range = getSelection().getRangeAt(0);
        if (element.isEqualNode(range.startContainer) || element.contains(range.startContainer)) {
            return range;
        }
    }
    if (vditor[vditor.currentMode].range) {
        return vditor[vditor.currentMode].range;
    }
    element.focus();
    range = element.ownerDocument.createRange();
    range.setStart(element, 0);
    range.collapse(true);
    return range;
};
var getCursorPosition = function (editor) {
    var range = window.getSelection().getRangeAt(0);
    if (!editor.contains(range.startContainer) && !(0,_hasClosest__WEBPACK_IMPORTED_MODULE_1__/* .hasClosestByClassName */ .fb)(range.startContainer, "vditor-panel--none")) {
        return {
            left: 0,
            top: 0,
        };
    }
    var parentRect = editor.parentElement.getBoundingClientRect();
    var cursorRect;
    if (range.getClientRects().length === 0) {
        if (range.startContainer.nodeType === 3) {
            // 空行时，会出现没有 br 的情况，需要根据父元素 <p> 获取位置信息
            var parent_1 = range.startContainer.parentElement;
            if (parent_1 && parent_1.getClientRects().length > 0) {
                cursorRect = parent_1.getClientRects()[0];
            }
            else {
                return {
                    left: 0,
                    top: 0,
                };
            }
        }
        else {
            var children = range.startContainer.children;
            if (children[range.startOffset] &&
                children[range.startOffset].getClientRects().length > 0) {
                // markdown 模式回车
                cursorRect = children[range.startOffset].getClientRects()[0];
            }
            else if (range.startContainer.childNodes.length > 0) {
                // in table or code block
                var cloneRange = range.cloneRange();
                range.selectNode(range.startContainer.childNodes[Math.max(0, range.startOffset - 1)]);
                cursorRect = range.getClientRects()[0];
                range.setEnd(cloneRange.endContainer, cloneRange.endOffset);
                range.setStart(cloneRange.startContainer, cloneRange.startOffset);
            }
            else {
                cursorRect = range.startContainer.getClientRects()[0];
            }
            if (!cursorRect) {
                var parentElement = range.startContainer.childNodes[range.startOffset];
                while (!parentElement.getClientRects ||
                    (parentElement.getClientRects && parentElement.getClientRects().length === 0)) {
                    parentElement = parentElement.parentElement;
                }
                cursorRect = parentElement.getClientRects()[0];
            }
        }
    }
    else {
        cursorRect = range.getClientRects()[0];
    }
    return {
        left: cursorRect.left - parentRect.left,
        top: cursorRect.top - parentRect.top,
    };
};
var selectIsEditor = function (editor, range) {
    if (!range) {
        if (getSelection().rangeCount === 0) {
            return false;
        }
        else {
            range = getSelection().getRangeAt(0);
        }
    }
    var container = range.commonAncestorContainer;
    return editor.isEqualNode(container) || editor.contains(container);
};
var setSelectionFocus = function (range) {
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
};
var getSelectPosition = function (selectElement, editorElement, range) {
    var position = {
        end: 0,
        start: 0,
    };
    if (!range) {
        if (getSelection().rangeCount === 0) {
            return position;
        }
        range = window.getSelection().getRangeAt(0);
    }
    if (selectIsEditor(editorElement, range)) {
        var preSelectionRange = range.cloneRange();
        if (selectElement.childNodes[0] && selectElement.childNodes[0].childNodes[0]) {
            preSelectionRange.setStart(selectElement.childNodes[0].childNodes[0], 0);
        }
        else {
            preSelectionRange.selectNodeContents(selectElement);
        }
        preSelectionRange.setEnd(range.startContainer, range.startOffset);
        position.start = preSelectionRange.toString().length;
        position.end = position.start + range.toString().length;
    }
    return position;
};
var setSelectionByPosition = function (start, end, editor) {
    var charIndex = 0;
    var line = 0;
    var pNode = editor.childNodes[line];
    var foundStart = false;
    var stop = false;
    start = Math.max(0, start);
    end = Math.max(0, end);
    var range = editor.ownerDocument.createRange();
    range.setStart(pNode || editor, 0);
    range.collapse(true);
    while (!stop && pNode) {
        var nextCharIndex = charIndex + pNode.textContent.length;
        if (!foundStart && start >= charIndex && start <= nextCharIndex) {
            if (start === 0) {
                range.setStart(pNode, 0);
            }
            else {
                if (pNode.childNodes[0].nodeType === 3) {
                    range.setStart(pNode.childNodes[0], start - charIndex);
                }
                else if (pNode.nextSibling) {
                    range.setStartBefore(pNode.nextSibling);
                }
                else {
                    range.setStartAfter(pNode);
                }
            }
            foundStart = true;
            if (start === end) {
                stop = true;
                break;
            }
        }
        if (foundStart && end >= charIndex && end <= nextCharIndex) {
            if (end === 0) {
                range.setEnd(pNode, 0);
            }
            else {
                if (pNode.childNodes[0].nodeType === 3) {
                    range.setEnd(pNode.childNodes[0], end - charIndex);
                }
                else if (pNode.nextSibling) {
                    range.setEndBefore(pNode.nextSibling);
                }
                else {
                    range.setEndAfter(pNode);
                }
            }
            stop = true;
        }
        charIndex = nextCharIndex;
        pNode = editor.childNodes[++line];
    }
    if (!stop && editor.childNodes[line - 1]) {
        range.setStartBefore(editor.childNodes[line - 1]);
    }
    setSelectionFocus(range);
    return range;
};
var setRangeByWbr = function (element, range) {
    var wbrElement = element.querySelector("wbr");
    if (!wbrElement) {
        return;
    }
    if (!wbrElement.previousElementSibling) {
        if (wbrElement.previousSibling) {
            // text<wbr>
            range.setStart(wbrElement.previousSibling, wbrElement.previousSibling.textContent.length);
        }
        else if (wbrElement.nextSibling) {
            if (wbrElement.nextSibling.nodeType === 3) {
                // <wbr>text
                range.setStart(wbrElement.nextSibling, 0);
            }
            else {
                // <wbr><br> https://github.com/Vanessa219/vditor/issues/400
                range.setStartBefore(wbrElement.nextSibling);
            }
        }
        else {
            // 内容为空
            range.setStart(wbrElement.parentElement, 0);
        }
    }
    else {
        if (wbrElement.previousElementSibling.isSameNode(wbrElement.previousSibling)) {
            if (wbrElement.previousElementSibling.lastChild) {
                // <em>text</em><wbr>
                range.setStartBefore(wbrElement);
                range.collapse(true);
                setSelectionFocus(range);
                // fix Chrome set range bug: **c**
                if ((0,_compatibility__WEBPACK_IMPORTED_MODULE_2__/* .isChrome */ .i7)() && (wbrElement.previousElementSibling.tagName === "EM" ||
                    wbrElement.previousElementSibling.tagName === "STRONG" ||
                    wbrElement.previousElementSibling.tagName === "S")) {
                    range.insertNode(document.createTextNode(_constants__WEBPACK_IMPORTED_MODULE_0__/* .Constants.ZWSP */ .g.ZWSP));
                    range.collapse(false);
                }
                wbrElement.remove();
                return;
            }
            else {
                // <br><wbr>
                range.setStartAfter(wbrElement.previousElementSibling);
            }
        }
        else {
            // <em>text</em>text<wbr>
            range.setStart(wbrElement.previousSibling, wbrElement.previousSibling.textContent.length);
        }
    }
    range.collapse(true);
    wbrElement.remove();
    setSelectionFocus(range);
};
var insertHTML = function (html, vditor) {
    // 使用 lute 方法会添加 p 元素，只有一个 p 元素的时候进行删除
    var tempElement = document.createElement("div");
    tempElement.innerHTML = html;
    var tempBlockElement = tempElement.querySelectorAll("p");
    if (tempBlockElement.length === 1 && !tempBlockElement[0].previousSibling && !tempBlockElement[0].nextSibling &&
        vditor[vditor.currentMode].element.children.length > 0 && tempElement.firstElementChild.tagName === "P") {
        html = tempBlockElement[0].innerHTML.trim();
    }
    var pasteElement = document.createElement("div");
    pasteElement.innerHTML = html;
    var range = getEditorRange(vditor);
    if (range.toString() !== "") {
        vditor[vditor.currentMode].preventInput = true;
        document.execCommand("delete", false, "");
    }
    if (pasteElement.firstElementChild &&
        pasteElement.firstElementChild.getAttribute("data-block") === "0") {
        // 粘贴内容为块元素时，应在下一段落中插入
        pasteElement.lastElementChild.insertAdjacentHTML("beforeend", "<wbr>");
        var blockElement = (0,_hasClosest__WEBPACK_IMPORTED_MODULE_1__/* .hasClosestBlock */ .F9)(range.startContainer);
        if (!blockElement) {
            vditor[vditor.currentMode].element.insertAdjacentHTML("beforeend", pasteElement.innerHTML);
        }
        else {
            blockElement.insertAdjacentHTML("afterend", pasteElement.innerHTML);
        }
        setRangeByWbr(vditor[vditor.currentMode].element, range);
    }
    else {
        var pasteTemplate = document.createElement("template");
        pasteTemplate.innerHTML = html;
        range.insertNode(pasteTemplate.content.cloneNode(true));
        range.collapse(false);
        setSelectionFocus(range);
    }
};


/***/ })

/******/ 	});
/************************************************************************/
/******/ 	// The module cache
/******/ 	var __webpack_module_cache__ = {};
/******/ 	
/******/ 	// The require function
/******/ 	function __webpack_require__(moduleId) {
/******/ 		// Check if module is in cache
/******/ 		var cachedModule = __webpack_module_cache__[moduleId];
/******/ 		if (cachedModule !== undefined) {
/******/ 			return cachedModule.exports;
/******/ 		}
/******/ 		// Create a new module (and put it into the cache)
/******/ 		var module = __webpack_module_cache__[moduleId] = {
/******/ 			// no module.id needed
/******/ 			// no module.loaded needed
/******/ 			exports: {}
/******/ 		};
/******/ 	
/******/ 		// Execute the module function
/******/ 		__webpack_modules__[moduleId](module, module.exports, __webpack_require__);
/******/ 	
/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}
/******/ 	
/************************************************************************/
/******/ 	/* webpack/runtime/define property getters */
/******/ 	(() => {
/******/ 		// define getter functions for harmony exports
/******/ 		__webpack_require__.d = (exports, definition) => {
/******/ 			for(var key in definition) {
/******/ 				if(__webpack_require__.o(definition, key) && !__webpack_require__.o(exports, key)) {
/******/ 					Object.defineProperty(exports, key, { enumerable: true, get: definition[key] });
/******/ 				}
/******/ 			}
/******/ 		};
/******/ 	})();
/******/ 	
/******/ 	/* webpack/runtime/hasOwnProperty shorthand */
/******/ 	(() => {
/******/ 		__webpack_require__.o = (obj, prop) => (Object.prototype.hasOwnProperty.call(obj, prop))
/******/ 	})();
/******/ 	
/******/ 	/* webpack/runtime/make namespace object */
/******/ 	(() => {
/******/ 		// define __esModule on exports
/******/ 		__webpack_require__.r = (exports) => {
/******/ 			if(typeof Symbol !== 'undefined' && Symbol.toStringTag) {
/******/ 				Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });
/******/ 			}
/******/ 			Object.defineProperty(exports, '__esModule', { value: true });
/******/ 		};
/******/ 	})();
/******/ 	
/************************************************************************/
var __webpack_exports__ = {};
// This entry need to be wrapped in an IIFE because it need to be in strict mode.
(() => {
"use strict";

// EXPORTS
__webpack_require__.d(__webpack_exports__, {
  "default": () => (/* binding */ src)
});

// EXTERNAL MODULE: ./src/method.ts + 4 modules
var method = __webpack_require__(664);
// EXTERNAL MODULE: ./src/ts/constants.ts
var constants = __webpack_require__(793);
// EXTERNAL MODULE: ./src/ts/util/code160to32.ts
var code160to32 = __webpack_require__(528);
;// CONCATENATED MODULE: ./src/ts/markdown/getMarkdown.ts

var getMarkdown = function (vditor) {
    if (vditor.currentMode === "sv") {
        return (0,code160to32/* code160to32 */.X)("".concat(vditor.sv.element.textContent, "\n").replace(/\n\n$/, "\n"));
    }
    else if (vditor.currentMode === "wysiwyg") {
        return vditor.lute.VditorDOM2Md(vditor.wysiwyg.element.innerHTML);
    }
    else if (vditor.currentMode === "ir") {
        return vditor.lute.VditorIRDOM2Md(vditor.ir.element.innerHTML);
    }
    return "";
};

// EXTERNAL MODULE: ./src/ts/util/addScript.ts
var addScript = __webpack_require__(998);
;// CONCATENATED MODULE: ./src/ts/devtools/index.ts


var DevTools = /** @class */ (function () {
    function DevTools() {
        this.element = document.createElement("div");
        this.element.className = "vditor-devtools";
        this.element.innerHTML = '<div class="vditor-reset--error"></div><div style="height: 100%;"></div>';
    }
    DevTools.prototype.renderEchart = function (vditor) {
        var _this = this;
        if (vditor.devtools.element.style.display !== "block") {
            return;
        }
        (0,addScript/* addScript */.G)("".concat(vditor.options.cdn, "/dist/js/echarts/echarts.min.js"), "vditorEchartsScript").then(function () {
            if (!_this.ASTChart) {
                _this.ASTChart = echarts.init(vditor.devtools.element.lastElementChild);
            }
            try {
                _this.element.lastElementChild.style.display = "block";
                _this.element.firstElementChild.innerHTML = "";
                _this.ASTChart.setOption({
                    series: [
                        {
                            data: JSON.parse(vditor.lute.RenderEChartsJSON(getMarkdown(vditor))),
                            initialTreeDepth: -1,
                            label: {
                                align: "left",
                                backgroundColor: "rgba(68, 77, 86, .68)",
                                borderRadius: 3,
                                color: "#d1d5da",
                                fontSize: 12,
                                lineHeight: 12,
                                offset: [9, 12],
                                padding: [2, 4, 2, 4],
                                position: "top",
                                verticalAlign: "middle",
                            },
                            lineStyle: {
                                color: "#4285f4",
                                type: "curve",
                                width: 1,
                            },
                            orient: "vertical",
                            roam: true,
                            type: "tree",
                        },
                    ],
                    toolbox: {
                        bottom: 25,
                        emphasis: {
                            iconStyle: {
                                color: "#4285f4",
                            },
                        },
                        feature: {
                            restore: {
                                show: true,
                            },
                            saveAsImage: {
                                show: true,
                            },
                        },
                        right: 15,
                        show: true,
                    },
                });
                _this.ASTChart.resize();
            }
            catch (e) {
                _this.element.lastElementChild.style.display = "none";
                _this.element.firstElementChild.innerHTML = e;
            }
        });
    };
    return DevTools;
}());


// EXTERNAL MODULE: ./src/ts/util/compatibility.ts
var compatibility = __webpack_require__(796);
;// CONCATENATED MODULE: ./src/ts/toolbar/setToolbar.ts


var removeCurrentToolbar = function (toolbar, names) {
    names.forEach(function (name) {
        if (!toolbar[name]) {
            return;
        }
        var itemElement = toolbar[name].children[0];
        if (itemElement && itemElement.classList.contains("vditor-menu--current")) {
            itemElement.classList.remove("vditor-menu--current");
        }
    });
};
var setCurrentToolbar = function (toolbar, names) {
    names.forEach(function (name) {
        if (!toolbar[name]) {
            return;
        }
        var itemElement = toolbar[name].children[0];
        if (itemElement && !itemElement.classList.contains("vditor-menu--current")) {
            itemElement.classList.add("vditor-menu--current");
        }
    });
};
var enableToolbar = function (toolbar, names) {
    names.forEach(function (name) {
        if (!toolbar[name]) {
            return;
        }
        var itemElement = toolbar[name].children[0];
        if (itemElement && itemElement.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
            itemElement.classList.remove(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED);
        }
    });
};
var disableToolbar = function (toolbar, names) {
    names.forEach(function (name) {
        if (!toolbar[name]) {
            return;
        }
        var itemElement = toolbar[name].children[0];
        if (itemElement && !itemElement.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
            itemElement.classList.add(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED);
        }
    });
};
var hideToolbar = function (toolbar, names) {
    names.forEach(function (name) {
        if (!toolbar[name]) {
            return;
        }
        if (toolbar[name]) {
            toolbar[name].style.display = "none";
        }
    });
};
var showToolbar = function (toolbar, names) {
    names.forEach(function (name) {
        if (!toolbar[name]) {
            return;
        }
        if (toolbar[name]) {
            toolbar[name].style.display = "block";
        }
    });
};
// "subToolbar", "hint", "popover"
var hidePanel = function (vditor, panels, exceptElement) {
    if (panels.includes("subToolbar")) {
        vditor.toolbar.element.querySelectorAll(".vditor-hint").forEach(function (item) {
            if (exceptElement && item.isEqualNode(exceptElement)) {
                return;
            }
            item.style.display = "none";
        });
        if (vditor.toolbar.elements.emoji) {
            vditor.toolbar.elements.emoji.lastElementChild.style.display = "none";
        }
    }
    if (panels.includes("hint")) {
        vditor.hint.element.style.display = "none";
    }
    if (vditor.wysiwyg.popover && panels.includes("popover")) {
        vditor.wysiwyg.popover.style.display = "none";
    }
};
var toggleSubMenu = function (vditor, panelElement, actionBtn, level) {
    actionBtn.addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (actionBtn.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
            return;
        }
        vditor.toolbar.element.querySelectorAll(".vditor-hint--current").forEach(function (item) {
            item.classList.remove("vditor-hint--current");
        });
        if (panelElement.style.display === "block") {
            panelElement.style.display = "none";
        }
        else {
            hidePanel(vditor, ["subToolbar", "hint", "popover"], actionBtn.parentElement.parentElement);
            if (!actionBtn.classList.contains("vditor-tooltipped")) {
                actionBtn.classList.add("vditor-hint--current");
            }
            panelElement.style.display = "block";
            if (vditor.toolbar.element.getBoundingClientRect().right - actionBtn.getBoundingClientRect().right < 250) {
                panelElement.classList.add("vditor-panel--left");
            }
            else {
                panelElement.classList.remove("vditor-panel--left");
            }
        }
    });
};

// EXTERNAL MODULE: ./src/ts/util/hasClosest.ts
var hasClosest = __webpack_require__(118);
// EXTERNAL MODULE: ./src/ts/util/hasClosestByHeadings.ts
var hasClosestByHeadings = __webpack_require__(946);
;// CONCATENATED MODULE: ./src/ts/util/log.ts
var log = function (method, content, type, print) {
    if (print) {
        // @ts-ignore
        console.log("".concat(method, " - ").concat(type, ": ").concat(content));
    }
};

// EXTERNAL MODULE: ./src/ts/markdown/abcRender.ts
var abcRender = __webpack_require__(386);
// EXTERNAL MODULE: ./src/ts/markdown/chartRender.ts
var chartRender = __webpack_require__(379);
// EXTERNAL MODULE: ./src/ts/markdown/codeRender.ts
var codeRender = __webpack_require__(895);
// EXTERNAL MODULE: ./src/ts/markdown/flowchartRender.ts
var flowchartRender = __webpack_require__(169);
// EXTERNAL MODULE: ./src/ts/markdown/graphvizRender.ts
var graphvizRender = __webpack_require__(572);
// EXTERNAL MODULE: ./src/ts/markdown/highlightRender.ts
var highlightRender = __webpack_require__(702);
// EXTERNAL MODULE: ./src/ts/markdown/mathRender.ts
var mathRender = __webpack_require__(982);
// EXTERNAL MODULE: ./src/ts/markdown/mermaidRender.ts
var mermaidRender = __webpack_require__(570);
// EXTERNAL MODULE: ./src/ts/markdown/markmapRender.ts
var markmapRender = __webpack_require__(593);
// EXTERNAL MODULE: ./src/ts/markdown/mindmapRender.ts
var mindmapRender = __webpack_require__(558);
// EXTERNAL MODULE: ./src/ts/markdown/plantumlRender.ts
var plantumlRender = __webpack_require__(931);
;// CONCATENATED MODULE: ./src/ts/util/processCode.ts











var processPasteCode = function (html, text, type) {
    if (type === void 0) { type = "sv"; }
    var tempElement = document.createElement("div");
    tempElement.innerHTML = html;
    var isCode = false;
    if (tempElement.childElementCount === 1 &&
        tempElement.lastElementChild.style.fontFamily.indexOf("monospace") > -1) {
        // VS Code
        isCode = true;
    }
    var pres = tempElement.querySelectorAll("pre");
    if (tempElement.childElementCount === 1 && pres.length === 1
        && pres[0].className !== "vditor-wysiwyg"
        && pres[0].className !== "vditor-sv") {
        // IDE
        isCode = true;
    }
    if (html.indexOf('\n<p class="p1">') === 0) {
        // Xcode
        isCode = true;
    }
    if (tempElement.childElementCount === 1 && tempElement.firstElementChild.tagName === "TABLE" &&
        tempElement.querySelector(".line-number") && tempElement.querySelector(".line-content")) {
        // 网页源码
        isCode = true;
    }
    if (isCode) {
        var code = text || html;
        if (/\n/.test(code) || pres.length === 1) {
            if (type === "wysiwyg") {
                return "<div class=\"vditor-wysiwyg__block\" data-block=\"0\" data-type=\"code-block\"><pre><code>".concat(code.replace(/&/g, "&amp;").replace(/</g, "&lt;"), "<wbr></code></pre></div>");
            }
            return "\n```\n" + code.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "\n```";
        }
        else {
            if (type === "wysiwyg") {
                return "<code>".concat(code.replace(/&/g, "&amp;").replace(/</g, "&lt;"), "</code><wbr>");
            }
            return "`".concat(code, "`");
        }
    }
    return false;
};
var processCodeRender = function (previewPanel, vditor) {
    if (!previewPanel) {
        return;
    }
    if (previewPanel.parentElement.getAttribute("data-type") === "html-block") {
        previewPanel.setAttribute("data-render", "1");
        return;
    }
    var language = previewPanel.firstElementChild.className.replace("language-", "");
    if (language === "abc") {
        (0,abcRender/* abcRender */.Q)(previewPanel, vditor.options.cdn);
    }
    else if (language === "mermaid") {
        (0,mermaidRender/* mermaidRender */.i)(previewPanel, vditor.options.cdn, vditor.options.theme);
    }
    else if (language === "markmap") {
        (0,markmapRender/* markmapRender */.K)(previewPanel, vditor.options.cdn, vditor.options.theme);
    }
    else if (language === "flowchart") {
        (0,flowchartRender/* flowchartRender */.P)(previewPanel, vditor.options.cdn);
    }
    else if (language === "echarts") {
        (0,chartRender/* chartRender */.p)(previewPanel, vditor.options.cdn, vditor.options.theme);
    }
    else if (language === "mindmap") {
        (0,mindmapRender/* mindmapRender */.P)(previewPanel, vditor.options.cdn, vditor.options.theme);
    }
    else if (language === "plantuml") {
        (0,plantumlRender/* plantumlRender */.B)(previewPanel, vditor.options.cdn);
    }
    else if (language === "graphviz") {
        (0,graphvizRender/* graphvizRender */.v)(previewPanel, vditor.options.cdn);
    }
    else if (language === "math") {
        (0,mathRender/* mathRender */.H)(previewPanel, { cdn: vditor.options.cdn, math: vditor.options.preview.math });
    }
    else {
        var cRender = vditor.options.customRenders.find(function (item) {
            if (item.language === language) {
                item.render(previewPanel, vditor);
                return true;
            }
        });
        if (!cRender) {
            (0,highlightRender/* highlightRender */.s)(Object.assign({}, vditor.options.preview.hljs), previewPanel, vditor.options.cdn);
            (0,codeRender/* codeRender */.O)(previewPanel, vditor.options.preview.hljs);
        }
    }
    previewPanel.setAttribute("data-render", "1");
};

// EXTERNAL MODULE: ./src/ts/util/selection.ts
var selection = __webpack_require__(307);
;// CONCATENATED MODULE: ./src/ts/util/toc.ts




var renderToc = function (vditor) {
    if (vditor.currentMode === "sv") {
        return;
    }
    var editorElement = vditor[vditor.currentMode].element;
    var tocHTML = vditor.outline.render(vditor);
    if (tocHTML === "") {
        tocHTML = "[ToC]";
    }
    editorElement.querySelectorAll('[data-type="toc-block"]').forEach(function (item) {
        item.innerHTML = tocHTML;
        (0,mathRender/* mathRender */.H)(item, {
            cdn: vditor.options.cdn,
            math: vditor.options.preview.math,
        });
    });
};
var clickToc = function (event, vditor) {
    var spanElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(event.target, "SPAN");
    if (spanElement && (0,hasClosest/* hasClosestByClassName */.fb)(spanElement, "vditor-toc")) {
        var headingElement = vditor[vditor.currentMode].element.querySelector("#" + spanElement.getAttribute("data-target-id"));
        if (headingElement) {
            if (vditor.options.height === "auto") {
                var windowScrollY = headingElement.offsetTop + vditor.element.offsetTop;
                if (!vditor.options.toolbarConfig.pin) {
                    windowScrollY += vditor.toolbar.element.offsetHeight;
                }
                window.scrollTo(window.scrollX, windowScrollY);
            }
            else {
                if (vditor.element.offsetTop < window.scrollY) {
                    window.scrollTo(window.scrollX, vditor.element.offsetTop);
                }
                vditor[vditor.currentMode].element.scrollTop = headingElement.offsetTop;
            }
        }
        return;
    }
};
var keydownToc = function (blockElement, vditor, event, range) {
    // toc 前无元素，插入空块
    if (blockElement.previousElementSibling &&
        blockElement.previousElementSibling.classList.contains("vditor-toc")) {
        if (event.key === "Backspace" &&
            (0,selection/* getSelectPosition */.im)(blockElement, vditor[vditor.currentMode].element, range).start === 0) {
            blockElement.previousElementSibling.remove();
            execAfterRender(vditor);
            return true;
        }
        if (insertBeforeBlock(vditor, event, range, blockElement, blockElement.previousElementSibling)) {
            return true;
        }
    }
    // toc 后无元素，插入空块
    if (blockElement.nextElementSibling &&
        blockElement.nextElementSibling.classList.contains("vditor-toc")) {
        if (event.key === "Delete" &&
            (0,selection/* getSelectPosition */.im)(blockElement, vditor[vditor.currentMode].element, range).start
                >= blockElement.textContent.trimRight().length) {
            blockElement.nextElementSibling.remove();
            execAfterRender(vditor);
            return true;
        }
        if (insertAfterBlock(vditor, event, range, blockElement, blockElement.nextElementSibling)) {
            return true;
        }
    }
    // toc 删除
    if (event.key === "Backspace" || event.key === "Delete") {
        var tocElement = (0,hasClosest/* hasClosestByClassName */.fb)(range.startContainer, "vditor-toc");
        if (tocElement) {
            tocElement.remove();
            execAfterRender(vditor);
            return true;
        }
    }
};

;// CONCATENATED MODULE: ./src/ts/ir/input.ts










var input = function (vditor, range, ignoreSpace, event) {
    if (ignoreSpace === void 0) { ignoreSpace = false; }
    var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
    // 前后可以输入空格
    if (blockElement && !ignoreSpace && blockElement.getAttribute("data-type") !== "code-block") {
        if ((isHrMD(blockElement.innerHTML) && blockElement.previousElementSibling) ||
            isHeadingMD(blockElement.innerHTML)) {
            return;
        }
        // 前后空格处理
        var startOffset = (0,selection/* getSelectPosition */.im)(blockElement, vditor.ir.element, range).start;
        // 开始可以输入空格
        var startSpace = true;
        for (var i = startOffset - 1; 
        // 软换行后有空格
        i > blockElement.textContent.substr(0, startOffset).lastIndexOf("\n"); i--) {
            if (blockElement.textContent.charAt(i) !== " " &&
                // 多个 tab 前删除不形成代码块 https://github.com/Vanessa219/vditor/issues/162 1
                blockElement.textContent.charAt(i) !== "\t") {
                startSpace = false;
                break;
            }
        }
        if (startOffset === 0) {
            startSpace = false;
        }
        // 结尾可以输入空格
        var endSpace = true;
        for (var i = startOffset - 1; i < blockElement.textContent.length; i++) {
            if (blockElement.textContent.charAt(i) !== " " && blockElement.textContent.charAt(i) !== "\n") {
                endSpace = false;
                break;
            }
        }
        if (startSpace) {
            if (typeof vditor.options.input === "function") {
                vditor.options.input(getMarkdown(vditor));
            }
            return;
        }
        if (endSpace) {
            var markerElement = (0,hasClosest/* hasClosestByClassName */.fb)(range.startContainer, "vditor-ir__marker");
            if (markerElement) {
                // inline marker space https://github.com/Vanessa219/vditor/issues/239
            }
            else {
                var previousNode = range.startContainer.previousSibling;
                if (previousNode && previousNode.nodeType !== 3 && previousNode.classList.contains("vditor-ir__node--expand")) {
                    // FireFox https://github.com/Vanessa219/vditor/issues/239
                    previousNode.classList.remove("vditor-ir__node--expand");
                }
                if (typeof vditor.options.input === "function") {
                    vditor.options.input(getMarkdown(vditor));
                }
                return;
            }
        }
    }
    vditor.ir.element.querySelectorAll(".vditor-ir__node--expand").forEach(function (item) {
        item.classList.remove("vditor-ir__node--expand");
    });
    if (!blockElement) {
        // 使用顶级块元素，应使用 innerHTML
        blockElement = vditor.ir.element;
    }
    // document.exeComment insertHTML 会插入 wbr
    if (!blockElement.querySelector("wbr")) {
        var previewRenderElement = (0,hasClosest/* hasClosestByClassName */.fb)(range.startContainer, "vditor-ir__preview");
        if (previewRenderElement) {
            previewRenderElement.previousElementSibling.insertAdjacentHTML("beforeend", "<wbr>");
        }
        else {
            range.insertNode(document.createElement("wbr"));
        }
    }
    // 清除浏览器自带的样式
    blockElement.querySelectorAll("[style]").forEach(function (item) {
        item.removeAttribute("style");
    });
    if (blockElement.getAttribute("data-type") === "link-ref-defs-block") {
        // 修改链接引用
        blockElement = vditor.ir.element;
    }
    var isIRElement = blockElement.isEqualNode(vditor.ir.element);
    var footnoteElement = (0,hasClosest/* hasClosestByAttribute */.a1)(blockElement, "data-type", "footnotes-block");
    var html = "";
    if (!isIRElement) {
        var blockquoteElement = (0,hasClosestByHeadings/* hasClosestByTag */.S)(range.startContainer, "BLOCKQUOTE");
        // 列表需要到最顶层
        var topListElement = (0,hasClosest/* getTopList */.O9)(range.startContainer);
        if (topListElement) {
            blockElement = topListElement;
        }
        // 应到引用层，否则 > --- 会解析为 front-matter；列表中有 blockquote 则解析 blockquote；blockquote 中有列表则解析列表
        if (blockquoteElement && (!topListElement || (topListElement && !blockquoteElement.contains(topListElement)))) {
            blockElement = blockquoteElement;
        }
        // 修改脚注
        if (footnoteElement) {
            blockElement = footnoteElement;
        }
        html = blockElement.outerHTML;
        if (blockElement.tagName === "UL" || blockElement.tagName === "OL") {
            // 如果为列表的话，需要把上下的列表都重绘
            var listPrevElement = blockElement.previousElementSibling;
            var listNextElement = blockElement.nextElementSibling;
            if (listPrevElement && (listPrevElement.tagName === "UL" || listPrevElement.tagName === "OL")) {
                html = listPrevElement.outerHTML + html;
                listPrevElement.remove();
            }
            if (listNextElement && (listNextElement.tagName === "UL" || listNextElement.tagName === "OL")) {
                html = html + listNextElement.outerHTML;
                listNextElement.remove();
            }
            // firefox 列表回车不会产生新的 list item https://github.com/Vanessa219/vditor/issues/194
            html = html.replace("<div><wbr><br></div>", "<li><p><wbr><br></p></li>");
        }
        else if (blockElement.previousElementSibling &&
            blockElement.previousElementSibling.textContent.replace(constants/* Constants.ZWSP */.g.ZWSP, "") !== "" &&
            event && event.inputType === "insertParagraph") {
            // 换行时需要处理上一段落
            html = blockElement.previousElementSibling.outerHTML + html;
            blockElement.previousElementSibling.remove();
        }
        if (!blockElement.innerText.startsWith("```")) {
            // 添加链接引用
            vditor.ir.element.querySelectorAll("[data-type='link-ref-defs-block']").forEach(function (item) {
                if (item && !blockElement.isEqualNode(item)) {
                    html += item.outerHTML;
                    item.remove();
                }
            });
            // 添加脚注
            vditor.ir.element.querySelectorAll("[data-type='footnotes-block']").forEach(function (item) {
                if (item && !blockElement.isEqualNode(item)) {
                    html += item.outerHTML;
                    item.remove();
                }
            });
        }
    }
    else {
        html = blockElement.innerHTML;
    }
    log("SpinVditorIRDOM", html, "argument", vditor.options.debugger);
    html = vditor.lute.SpinVditorIRDOM(html);
    log("SpinVditorIRDOM", html, "result", vditor.options.debugger);
    if (isIRElement) {
        blockElement.innerHTML = html;
    }
    else {
        blockElement.outerHTML = html;
        // 更新正文中的 tip
        if (footnoteElement) {
            var footnoteItemElement = (0,hasClosest/* hasClosestByAttribute */.a1)(vditor.ir.element.querySelector("wbr"), "data-type", "footnotes-def");
            if (footnoteItemElement) {
                var footnoteItemText = footnoteItemElement.textContent;
                var marker = footnoteItemText.substring(1, footnoteItemText.indexOf("]:"));
                var footnoteRefElement = vditor.ir.element.querySelector("sup[data-type=\"footnotes-ref\"][data-footnotes-label=\"".concat(marker, "\"]"));
                if (footnoteRefElement) {
                    footnoteRefElement.setAttribute("aria-label", footnoteItemText.substr(marker.length + 3).trim().substr(0, 24));
                }
            }
        }
    }
    //  linkref 合并及添加
    var firstLinkRefDefElement;
    var allLinkRefDefsElement = vditor.ir.element.querySelectorAll("[data-type='link-ref-defs-block']");
    allLinkRefDefsElement.forEach(function (item, index) {
        if (index === 0) {
            firstLinkRefDefElement = item;
        }
        else {
            firstLinkRefDefElement.insertAdjacentHTML("beforeend", item.innerHTML);
            item.remove();
        }
    });
    if (allLinkRefDefsElement.length > 0) {
        vditor.ir.element.insertAdjacentElement("beforeend", allLinkRefDefsElement[0]);
    }
    // 脚注合并后添加的末尾
    var firstFootnoteElement;
    var allFootnoteElement = vditor.ir.element.querySelectorAll("[data-type='footnotes-block']");
    allFootnoteElement.forEach(function (item, index) {
        if (index === 0) {
            firstFootnoteElement = item;
        }
        else {
            firstFootnoteElement.insertAdjacentHTML("beforeend", item.innerHTML);
            item.remove();
        }
    });
    if (allFootnoteElement.length > 0) {
        vditor.ir.element.insertAdjacentElement("beforeend", allFootnoteElement[0]);
    }
    (0,selection/* setRangeByWbr */.ib)(vditor.ir.element, range);
    vditor.ir.element.querySelectorAll(".vditor-ir__preview[data-render='2']").forEach(function (item) {
        processCodeRender(item, vditor);
    });
    renderToc(vditor);
    process_processAfterRender(vditor, {
        enableAddUndoStack: true,
        enableHint: true,
        enableInput: true,
    });
};

;// CONCATENATED MODULE: ./src/ts/util/hotKey.ts

// 是否匹配 ⇧⌘[] / ⌘[] / ⌥[] / ⌥⌘[] / ⇧Tab / []
var matchHotKey = function (hotKey, event) {
    if (hotKey === "") {
        return false;
    }
    // []
    if (hotKey.indexOf("⇧") === -1 && hotKey.indexOf("⌘") === -1 && hotKey.indexOf("⌥") === -1) {
        if (!(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && !event.shiftKey && event.code === hotKey) {
            return true;
        }
        return false;
    }
    // 是否匹配 ⇧Tab
    if (hotKey === "⇧Tab") {
        if (!(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && event.shiftKey && event.code === "Tab") {
            return true;
        }
        return false;
    }
    var hotKeys = hotKey.split("");
    if (hotKey.startsWith("⌥")) {
        // 是否匹配 ⌥[] / ⌥⌘[]
        var keyCode = hotKeys.length === 3 ? hotKeys[2] : hotKeys[1];
        if ((hotKeys.length === 3 ? (0,compatibility/* isCtrl */.yl)(event) : !(0,compatibility/* isCtrl */.yl)(event)) && event.altKey && !event.shiftKey &&
            event.code === (/^[0-9]$/.test(keyCode) ? "Digit" : "Key") + keyCode) {
            return true;
        }
        return false;
    }
    // 是否匹配 ⇧⌘[] / ⌘[]
    if (hotKey === "⌘Enter") {
        hotKeys = ["⌘", "Enter"];
    }
    var hasShift = hotKeys.length > 2 && (hotKeys[0] === "⇧");
    var key = (hasShift ? hotKeys[2] : hotKeys[1]);
    if (hasShift && ((0,compatibility/* isFirefox */.vU)() || !/Mac/.test(navigator.platform))) {
        if (key === "-") {
            key = "_";
        }
        else if (key === "=") {
            key = "+";
        }
    }
    if ((0,compatibility/* isCtrl */.yl)(event) && event.key.toLowerCase() === key.toLowerCase() && !event.altKey
        && ((!hasShift && !event.shiftKey) || (hasShift && event.shiftKey))) {
        return true;
    }
    return false;
};

;// CONCATENATED MODULE: ./src/ts/ir/expandMarker.ts


var nextIsNode = function (range) {
    var startContainer = range.startContainer;
    if (startContainer.nodeType === 3 && startContainer.nodeValue.length !== range.startOffset) {
        return false;
    }
    var nextNode = startContainer.nextSibling;
    while (nextNode && nextNode.textContent === "") {
        nextNode = nextNode.nextSibling;
    }
    if (!nextNode) {
        // *em*|**string**
        var markerElement = (0,hasClosest/* hasClosestByClassName */.fb)(startContainer, "vditor-ir__marker");
        if (markerElement && !markerElement.nextSibling) {
            var parentNextNode = startContainer.parentElement.parentElement.nextSibling;
            if (parentNextNode && parentNextNode.nodeType !== 3 &&
                parentNextNode.classList.contains("vditor-ir__node")) {
                return parentNextNode;
            }
        }
        return false;
    }
    else if (nextNode && nextNode.nodeType !== 3 && nextNode.classList.contains("vditor-ir__node") &&
        !nextNode.getAttribute("data-block")) {
        // test|*em*
        return nextNode;
    }
    return false;
};
var previousIsNode = function (range) {
    var startContainer = range.startContainer;
    var previousNode = startContainer.previousSibling;
    if (startContainer.nodeType === 3 && range.startOffset === 0 && previousNode && previousNode.nodeType !== 3 &&
        // *em*|text
        previousNode.classList.contains("vditor-ir__node") && !previousNode.getAttribute("data-block")) {
        return previousNode;
    }
    return false;
};
var expandMarker = function (range, vditor) {
    vditor.ir.element.querySelectorAll(".vditor-ir__node--expand").forEach(function (item) {
        item.classList.remove("vditor-ir__node--expand");
    });
    var nodeElement = (0,hasClosest/* hasTopClosestByClassName */.JQ)(range.startContainer, "vditor-ir__node");
    var nodeElementEnd = !range.collapsed && (0,hasClosest/* hasTopClosestByClassName */.JQ)(range.endContainer, "vditor-ir__node");
    // 选中文本为同一个 nodeElement 内时，需要展开
    if (!range.collapsed && (!nodeElement || nodeElement !== nodeElementEnd)) {
        return;
    }
    if (nodeElement) {
        nodeElement.classList.add("vditor-ir__node--expand");
        nodeElement.classList.remove("vditor-ir__node--hidden");
        // https://github.com/Vanessa219/vditor/issues/615 safari中光标位置跳动
        (0,selection/* setSelectionFocus */.Hc)(range);
    }
    var nextNode = nextIsNode(range);
    if (nextNode) {
        nextNode.classList.add("vditor-ir__node--expand");
        nextNode.classList.remove("vditor-ir__node--hidden");
        return;
    }
    var previousNode = previousIsNode(range);
    if (previousNode) {
        previousNode.classList.add("vditor-ir__node--expand");
        previousNode.classList.remove("vditor-ir__node--hidden");
        return;
    }
};

;// CONCATENATED MODULE: ./src/ts/ir/processKeydown.ts











var processKeydown = function (vditor, event) {
    vditor.ir.composingLock = event.isComposing;
    if (event.isComposing) {
        return false;
    }
    // 添加第一次记录 undo 的光标
    if (event.key.indexOf("Arrow") === -1 && event.key !== "Meta" && event.key !== "Control" && event.key !== "Alt" &&
        event.key !== "Shift" && event.key !== "CapsLock" && event.key !== "Escape" && !/^F\d{1,2}$/.test(event.key)) {
        vditor.undo.recordFirstPosition(vditor, event);
    }
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var startContainer = range.startContainer;
    if (!fixGSKeyBackspace(event, vditor, startContainer)) {
        return false;
    }
    fixCJKPosition(range, vditor, event);
    fixHR(range);
    // 仅处理以下快捷键操作
    if (event.key !== "Enter" && event.key !== "Tab" && event.key !== "Backspace" && event.key.indexOf("Arrow") === -1
        && !(0,compatibility/* isCtrl */.yl)(event) && event.key !== "Escape" && event.key !== "Delete") {
        return false;
    }
    // 斜体、粗体、内联代码块中换行
    var newlineElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-newline", "1");
    if (!(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && !event.shiftKey && event.key === "Enter" && newlineElement
        && range.startOffset < newlineElement.textContent.length) {
        var beforeMarkerElement = newlineElement.previousElementSibling;
        if (beforeMarkerElement) {
            range.insertNode(document.createTextNode(beforeMarkerElement.textContent));
            range.collapse(false);
        }
        var afterMarkerElement = newlineElement.nextSibling;
        if (afterMarkerElement) {
            range.insertNode(document.createTextNode(afterMarkerElement.textContent));
            range.collapse(true);
        }
    }
    var pElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "P");
    // md 处理
    if (fixMarkdown(event, vditor, pElement, range)) {
        return true;
    }
    // li
    if (fixList(range, vditor, pElement, event)) {
        return true;
    }
    // blockquote
    if (fixBlockquote(vditor, range, event, pElement)) {
        return true;
    }
    // 代码块
    var preRenderElement = (0,hasClosest/* hasClosestByClassName */.fb)(startContainer, "vditor-ir__marker--pre");
    if (preRenderElement && preRenderElement.tagName === "PRE") {
        var codeRenderElement = preRenderElement.firstChild;
        if (fixCodeBlock(vditor, event, preRenderElement, range)) {
            return true;
        }
        // 数学公式上无元素，按上或左将添加新块
        if ((codeRenderElement.getAttribute("data-type") === "math-block"
            || codeRenderElement.getAttribute("data-type") === "html-block") &&
            insertBeforeBlock(vditor, event, range, codeRenderElement, preRenderElement.parentElement)) {
            return true;
        }
        // 代码块下无元素或者为代码块/table 元素，添加空块
        if (insertAfterBlock(vditor, event, range, codeRenderElement, preRenderElement.parentElement)) {
            return true;
        }
    }
    // 代码块语言
    var preBeforeElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "code-block-info");
    if (preBeforeElement) {
        if (event.key === "Enter" || event.key === "Tab") {
            range.selectNodeContents(preBeforeElement.nextElementSibling.firstChild);
            range.collapse(true);
            event.preventDefault();
            hidePanel(vditor, ["hint"]);
            return true;
        }
        if (event.key === "Backspace") {
            var start = (0,selection/* getSelectPosition */.im)(preBeforeElement, vditor.ir.element).start;
            if (start === 1) { // 删除零宽空格
                range.setStart(startContainer, 0);
            }
            if (start === 2) { // 删除时清空自动补全语言
                vditor.hint.recentLanguage = "";
            }
        }
        if (insertBeforeBlock(vditor, event, range, preBeforeElement, preBeforeElement.parentElement)) {
            // 上无元素，按上或左将添加新块
            hidePanel(vditor, ["hint"]);
            return true;
        }
    }
    // table
    var cellElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TD") ||
        (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TH");
    if (event.key.indexOf("Arrow") > -1 && cellElement) {
        var tableElement = isFirstCell(cellElement);
        if (tableElement && insertBeforeBlock(vditor, event, range, cellElement, tableElement)) {
            return true;
        }
        var table2Element = isLastCell(cellElement);
        if (table2Element && insertAfterBlock(vditor, event, range, cellElement, table2Element)) {
            return true;
        }
    }
    if (fixTable(vditor, event, range)) {
        return true;
    }
    // task list
    if (fixTask(vditor, range, event)) {
        return true;
    }
    // tab
    if (fixTab(vditor, range, event)) {
        return true;
    }
    var headingElement = (0,hasClosestByHeadings/* hasClosestByHeadings */.W)(startContainer);
    if (headingElement) {
        // enter++: 标题变大
        if (matchHotKey("⌘=", event)) {
            var headingMarkerElement = headingElement.querySelector(".vditor-ir__marker--heading");
            if (headingMarkerElement && headingMarkerElement.textContent.trim().length > 1) {
                process_processHeading(vditor, headingMarkerElement.textContent.substr(1));
            }
            event.preventDefault();
            return true;
        }
        // enter++: 标题变小
        if (matchHotKey("⌘-", event)) {
            var headingMarkerElement = headingElement.querySelector(".vditor-ir__marker--heading");
            if (headingMarkerElement && headingMarkerElement.textContent.trim().length < 6) {
                process_processHeading(vditor, headingMarkerElement.textContent.trim() + "# ");
            }
            event.preventDefault();
            return true;
        }
    }
    var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(startContainer);
    if (event.key === "Backspace" && !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey && range.toString() === "") {
        if (fixDelete(vditor, range, event, pElement)) {
            return true;
        }
        if (blockElement && blockElement.previousElementSibling
            && blockElement.tagName !== "UL" && blockElement.tagName !== "OL"
            && (blockElement.previousElementSibling.getAttribute("data-type") === "code-block" ||
                blockElement.previousElementSibling.getAttribute("data-type") === "math-block")) {
            var rangeStart = (0,selection/* getSelectPosition */.im)(blockElement, vditor.ir.element, range).start;
            if (rangeStart === 0 || (rangeStart === 1 && blockElement.innerText.startsWith(constants/* Constants.ZWSP */.g.ZWSP))) {
                // 当前块删除后光标落于代码渲染块上，当前块会被删除，因此需要阻止事件，不能和 keyup 中的代码块处理合并
                range.selectNodeContents(blockElement.previousElementSibling.querySelector(".vditor-ir__marker--pre code"));
                range.collapse(false);
                expandMarker(range, vditor);
                if (blockElement.textContent.trim().replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "") {
                    // 当前块为空且不是最后一个时，需要删除
                    blockElement.remove();
                    process_processAfterRender(vditor);
                }
                event.preventDefault();
                return true;
            }
        }
        // 光标位于标题前，marker 后
        if (headingElement) {
            var headingLength = headingElement.firstElementChild.textContent.length;
            if ((0,selection/* getSelectPosition */.im)(headingElement, vditor.ir.element).start === headingLength) {
                range.setStart(headingElement.firstElementChild.firstChild, headingLength - 1);
                range.collapse(true);
                (0,selection/* setSelectionFocus */.Hc)(range);
            }
        }
    }
    if ((event.key === "ArrowUp" || event.key === "ArrowDown") && blockElement) {
        // https://github.com/Vanessa219/vditor/issues/358
        blockElement.querySelectorAll(".vditor-ir__node").forEach(function (item) {
            if (!item.contains(startContainer)) {
                item.classList.add("vditor-ir__node--hidden");
            }
        });
        if (fixFirefoxArrowUpTable(event, blockElement, range)) {
            return true;
        }
    }
    fixCursorDownInlineMath(range, event.key);
    if (blockElement && keydownToc(blockElement, vditor, event, range)) {
        event.preventDefault();
        return true;
    }
    return false;
};

// EXTERNAL MODULE: ./src/ts/preview/image.ts
var preview_image = __webpack_require__(971);
;// CONCATENATED MODULE: ./src/ts/sv/combineFootnote.ts
/**
 * 合并脚注
 * @param elements vditor.sv.element
 * @param afterCombine 每个脚注块合并完成后的回调, param: root为合并后的脚注块
 */
var combineFootnote = function (elements, afterCombine) {
    elements.querySelectorAll("[data-type=footnotes-link]").forEach(function (el) {
        var root = el.parentElement;
        var footnote = root.nextSibling;
        // 寻找所有该脚注的块
        while (footnote) {
            if (footnote.textContent.startsWith("    ")) {
                // 解析到四个空格，加入到root并继续解析
                var thisNode = footnote;
                thisNode.childNodes.forEach(function (node) {
                    root.append(node.cloneNode(true));
                });
                footnote = footnote.nextSibling;
                thisNode.remove();
            }
            else {
                // 非空格停止解析
                break;
            }
        }
        afterCombine && afterCombine(root);
    });
};

;// CONCATENATED MODULE: ./src/ts/sv/inputEvent.ts





var inputEvent = function (vditor, event) {
    var _a;
    var range = getSelection().getRangeAt(0).cloneRange();
    var startContainer = range.startContainer;
    if (range.startContainer.nodeType !== 3 && range.startContainer.tagName === "DIV") {
        startContainer = range.startContainer.childNodes[range.startOffset - 1];
    }
    var blockElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-block", "0");
    // 不调用 lute 解析
    if (blockElement && event && (event.inputType === "deleteContentBackward" || event.data === " ")) {
        // 开始可以输入空格
        var startOffset = (0,selection/* getSelectPosition */.im)(blockElement, vditor.sv.element, range).start;
        var startSpace = true;
        for (var i = startOffset - 1; 
        // 软换行后有空格
        i > blockElement.textContent.substr(0, startOffset).lastIndexOf("\n"); i--) {
            if (blockElement.textContent.charAt(i) !== " " &&
                // 多个 tab 前删除不形成代码块 https://github.com/Vanessa219/vditor/issues/162 1
                blockElement.textContent.charAt(i) !== "\t") {
                startSpace = false;
                break;
            }
        }
        if (startOffset === 0) {
            startSpace = false;
        }
        if (startSpace) {
            processAfterRender(vditor);
            return;
        }
        if (event.inputType === "deleteContentBackward") {
            // https://github.com/Vanessa219/vditor/issues/584 代码块 marker 删除
            var codeBlockMarkerElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "code-block-open-marker") ||
                (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "code-block-close-marker");
            if (codeBlockMarkerElement) {
                if (codeBlockMarkerElement.getAttribute("data-type") === "code-block-close-marker") {
                    var openMarkerElement = getSideByType(startContainer, "code-block-open-marker");
                    if (openMarkerElement) {
                        openMarkerElement.textContent = codeBlockMarkerElement.textContent;
                        processAfterRender(vditor);
                        return;
                    }
                }
                if (codeBlockMarkerElement.getAttribute("data-type") === "code-block-open-marker") {
                    var openMarkerElement = getSideByType(startContainer, "code-block-close-marker", false);
                    if (openMarkerElement) {
                        openMarkerElement.textContent = codeBlockMarkerElement.textContent;
                        processAfterRender(vditor);
                        return;
                    }
                }
            }
            // https://github.com/Vanessa219/vditor/issues/877 数学公式输入删除生成节点
            var mathBlockMarkerElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "math-block-open-marker");
            if (mathBlockMarkerElement) {
                var mathBlockCloseElement = mathBlockMarkerElement.nextElementSibling.nextElementSibling;
                if (mathBlockCloseElement && mathBlockCloseElement.getAttribute("data-type") === "math-block-close-marker") {
                    mathBlockCloseElement.remove();
                    processAfterRender(vditor);
                }
                return;
            }
            blockElement.querySelectorAll('[data-type="code-block-open-marker"]').forEach(function (item) {
                if (item.textContent.length === 1) {
                    item.remove();
                }
            });
            blockElement.querySelectorAll('[data-type="code-block-close-marker"]').forEach(function (item) {
                if (item.textContent.length === 1) {
                    item.remove();
                }
            });
            // 标题删除
            var headingElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "heading-marker");
            if (headingElement && headingElement.textContent.indexOf("#") === -1) {
                processAfterRender(vditor);
                return;
            }
        }
        // 删除或空格不解析，否则会 format 回去
        if ((event.data === " " || event.inputType === "deleteContentBackward") &&
            ((0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "padding") // 场景：b 前进行删除 [> 1. a\n>   b]
                || (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "li-marker") // 场景：删除最后一个字符 [* 1\n* ]
                || (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "task-marker") // 场景：删除最后一个字符 [* [ ] ]
                || (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "blockquote-marker") // 场景：删除最后一个字符 [> ]
            )) {
            processAfterRender(vditor);
            return;
        }
    }
    if (blockElement && blockElement.textContent.trimRight() === "$$") {
        // 内联数学公式
        processAfterRender(vditor);
        return;
    }
    if (!blockElement) {
        blockElement = vditor.sv.element;
    }
    if (((_a = blockElement.firstElementChild) === null || _a === void 0 ? void 0 : _a.getAttribute("data-type")) === "link-ref-defs-block") {
        // 修改链接引用
        blockElement = vditor.sv.element;
    }
    if ((0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "footnotes-link")) {
        // 修改脚注角标
        blockElement = vditor.sv.element;
    }
    // 添加光标位置
    if (blockElement.textContent.indexOf(Lute.Caret) === -1) {
        // 点击工具栏会插入 Caret
        range.insertNode(document.createTextNode(Lute.Caret));
    }
    // 清除浏览器自带的样式
    blockElement.querySelectorAll("[style]").forEach(function (item) {
        item.removeAttribute("style");
    });
    blockElement.querySelectorAll("font").forEach(function (item) {
        item.outerHTML = item.innerHTML;
    });
    var html = blockElement.textContent;
    var isSVElement = blockElement.isEqualNode(vditor.sv.element);
    if (isSVElement) {
        html = blockElement.textContent;
    }
    else {
        // 添加前一个块元素
        if (blockElement.previousElementSibling) {
            html = blockElement.previousElementSibling.textContent + html;
            blockElement.previousElementSibling.remove();
        }
        if (blockElement.previousElementSibling && html.indexOf("---\n") === 0) {
            // 确认 yaml-front 是否为首行
            html = blockElement.previousElementSibling.textContent + html;
            blockElement.previousElementSibling.remove();
        }
        // 添加链接引用
        var footnotes_1 = "";
        vditor.sv.element.querySelectorAll("[data-type='link-ref-defs-block']").forEach(function (item, index) {
            if (item && !blockElement.isEqualNode(item.parentElement)) {
                footnotes_1 += item.parentElement.textContent + "\n";
                item.parentElement.remove();
            }
        });
        // 添加脚注到文章头，便于lute处理
        vditor.sv.element.querySelectorAll("[data-type='footnotes-link']").forEach(function (item, index) {
            if (item && !blockElement.isEqualNode(item.parentElement)) {
                footnotes_1 += item.parentElement.textContent + "\n";
                item.parentElement.remove();
            }
        });
        html = footnotes_1 + html;
    }
    html = processSpinVditorSVDOM(html, vditor);
    if (isSVElement) {
        blockElement.innerHTML = html;
    }
    else {
        blockElement.outerHTML = html;
    }
    vditor.sv.element.querySelectorAll("[data-type='link-ref-defs-block']").forEach(function (item) {
        vditor.sv.element.insertAdjacentElement("beforeend", item.parentElement);
    });
    // 合并脚注
    combineFootnote(vditor.sv.element, function (root) {
        vditor.sv.element.insertAdjacentElement("beforeend", root);
    });
    (0,selection/* setRangeByWbr */.ib)(vditor.sv.element, range);
    scrollCenter(vditor);
    processAfterRender(vditor, {
        enableAddUndoStack: true,
        enableHint: true,
        enableInput: true,
    });
};

;// CONCATENATED MODULE: ./src/ts/sv/processKeydown.ts







var processKeydown_processKeydown = function (vditor, event) {
    var _a, _b, _c, _d, _e;
    vditor.sv.composingLock = event.isComposing;
    if (event.isComposing) {
        return false;
    }
    if (event.key.indexOf("Arrow") === -1 && event.key !== "Meta" && event.key !== "Control" && event.key !== "Alt" &&
        event.key !== "Shift" && event.key !== "CapsLock" && event.key !== "Escape" && !/^F\d{1,2}$/.test(event.key)) {
        vditor.undo.recordFirstPosition(vditor, event);
    }
    // 仅处理以下快捷键操作
    if (event.key !== "Enter" && event.key !== "Tab" && event.key !== "Backspace" && event.key.indexOf("Arrow") === -1
        && !(0,compatibility/* isCtrl */.yl)(event) && event.key !== "Escape") {
        return false;
    }
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var startContainer = range.startContainer;
    if (range.startContainer.nodeType !== 3 && range.startContainer.tagName === "DIV") {
        startContainer = range.startContainer.childNodes[range.startOffset - 1];
    }
    var textElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "text");
    // blockquote
    var blockquoteMarkerElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "blockquote-marker");
    if (!blockquoteMarkerElement && range.startOffset === 0 && textElement && textElement.previousElementSibling &&
        textElement.previousElementSibling.getAttribute("data-type") === "blockquote-marker") {
        blockquoteMarkerElement = textElement.previousElementSibling;
    }
    // 回车逐个删除 blockquote marker 标记
    if (blockquoteMarkerElement) {
        if (event.key === "Enter" && !(0,compatibility/* isCtrl */.yl)(event) && !event.altKey &&
            blockquoteMarkerElement.nextElementSibling.textContent.trim() === "" &&
            (0,selection/* getSelectPosition */.im)(blockquoteMarkerElement, vditor.sv.element, range).start ===
                blockquoteMarkerElement.textContent.length) {
            if (((_a = blockquoteMarkerElement.previousElementSibling) === null || _a === void 0 ? void 0 : _a.getAttribute("data-type")) === "padding") {
                // 列表中存在多行 BQ 时，标记回车需跳出列表
                blockquoteMarkerElement.previousElementSibling.setAttribute("data-action", "enter-remove");
            }
            blockquoteMarkerElement.remove();
            processAfterRender(vditor);
            event.preventDefault();
            return true;
        }
    }
    // list item
    var listMarkerElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "li-marker");
    var taskMarkerElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "task-marker");
    var listLastMarkerElement = listMarkerElement;
    if (!listLastMarkerElement) {
        if (taskMarkerElement && taskMarkerElement.nextElementSibling.getAttribute("data-type") !== "task-marker") {
            listLastMarkerElement = taskMarkerElement;
        }
    }
    if (!listLastMarkerElement && range.startOffset === 0 && textElement && textElement.previousElementSibling &&
        (textElement.previousElementSibling.getAttribute("data-type") === "li-marker" ||
            textElement.previousElementSibling.getAttribute("data-type") === "task-marker")) {
        listLastMarkerElement = textElement.previousElementSibling;
    }
    if (listLastMarkerElement) {
        var startIndex = (0,selection/* getSelectPosition */.im)(listLastMarkerElement, vditor.sv.element, range).start;
        var isTask = listLastMarkerElement.getAttribute("data-type") === "task-marker";
        var listFirstMarkerElement = listLastMarkerElement;
        if (isTask) {
            listFirstMarkerElement = listLastMarkerElement.previousElementSibling.previousElementSibling
                .previousElementSibling;
        }
        if (startIndex === listLastMarkerElement.textContent.length) {
            // 回车清空列表标记符
            if (event.key === "Enter" && !(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && !event.shiftKey &&
                listLastMarkerElement.nextElementSibling.textContent.trim() === "") {
                if (((_b = listFirstMarkerElement.previousElementSibling) === null || _b === void 0 ? void 0 : _b.getAttribute("data-type")) === "padding") {
                    listFirstMarkerElement.previousElementSibling.remove();
                    inputEvent(vditor);
                }
                else {
                    if (isTask) {
                        listFirstMarkerElement.remove();
                        listLastMarkerElement.previousElementSibling.previousElementSibling.remove();
                        listLastMarkerElement.previousElementSibling.remove();
                    }
                    listLastMarkerElement.nextElementSibling.remove();
                    listLastMarkerElement.remove();
                    processAfterRender(vditor);
                }
                event.preventDefault();
                return true;
            }
            // 第一个 marker 后 tab 进行缩进
            if (event.key === "Tab") {
                if (event.shiftKey) {
                    if (listFirstMarkerElement.previousElementSibling.getAttribute("data-type") === "padding") {
                        listFirstMarkerElement.previousElementSibling.remove();
                    }
                }
                else {
                    listFirstMarkerElement.insertAdjacentHTML("beforebegin", "<span data-type=\"padding\">".concat(listFirstMarkerElement.textContent.replace(/\S/g, " "), "</span>"));
                }
                if (/^\d/.test(listFirstMarkerElement.textContent)) {
                    listFirstMarkerElement.textContent = listFirstMarkerElement.textContent.replace(/^\d{1,}/, "1");
                    range.selectNodeContents(listLastMarkerElement.firstChild);
                    range.collapse(false);
                }
                inputEvent(vditor);
                event.preventDefault();
                return true;
            }
        }
    }
    // tab
    if (fixTab(vditor, range, event)) {
        return true;
    }
    var blockElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-block", "0");
    var spanElement = (0,hasClosestByHeadings/* hasClosestByTag */.S)(startContainer, "SPAN");
    // 回车
    if (event.key === "Enter" && !(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && !event.shiftKey && blockElement) {
        var isFirst = false;
        var newLineMatch = blockElement.textContent.match(/^\n+/);
        if ((0,selection/* getSelectPosition */.im)(blockElement, vditor.sv.element).start <= (newLineMatch ? newLineMatch[0].length : 0)) {
            // 允许段落开始换行
            isFirst = true;
        }
        var newLineText = "\n";
        if (spanElement) {
            if (((_c = spanElement.previousElementSibling) === null || _c === void 0 ? void 0 : _c.getAttribute("data-action")) === "enter-remove") {
                // https://github.com/Vanessa219/vditor/issues/596
                spanElement.previousElementSibling.remove();
                processAfterRender(vditor);
                event.preventDefault();
                return true;
            }
            else {
                newLineText += processPreviousMarkers(spanElement);
            }
        }
        range.insertNode(document.createTextNode(newLineText));
        range.collapse(false);
        if (blockElement && blockElement.textContent.trim() !== "" && !isFirst) {
            inputEvent(vditor);
        }
        else {
            processAfterRender(vditor);
        }
        event.preventDefault();
        return true;
    }
    // 删除后光标前有 newline 的处理
    if (event.key === "Backspace" && !(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && !event.shiftKey) {
        if (spanElement && ((_d = spanElement.previousElementSibling) === null || _d === void 0 ? void 0 : _d.getAttribute("data-type")) === "newline" &&
            (0,selection/* getSelectPosition */.im)(spanElement, vditor.sv.element, range).start === 1 &&
            // 飘号的处理需在 inputEvent 中，否则上下飘号对不齐
            spanElement.getAttribute("data-type").indexOf("code-block-") === -1) {
            // 光标在每一行的第一个字符后
            range.setStart(spanElement, 0);
            range.extractContents();
            if (spanElement.textContent.trim() !== "") {
                inputEvent(vditor);
            }
            else {
                processAfterRender(vditor);
            }
            event.preventDefault();
            return true;
        }
        // 每一段第一个字符前
        if (blockElement && (0,selection/* getSelectPosition */.im)(blockElement, vditor.sv.element, range).start === 0 &&
            blockElement.previousElementSibling) {
            range.extractContents();
            var previousLastElement = blockElement.previousElementSibling.lastElementChild;
            if (previousLastElement.getAttribute("data-type") === "newline") {
                previousLastElement.remove();
                previousLastElement = blockElement.previousElementSibling.lastElementChild;
            }
            // 场景：末尾无法删除 [```\ntext\n```\n\n]
            if (previousLastElement.getAttribute("data-type") !== "newline") {
                previousLastElement.insertAdjacentHTML("afterend", blockElement.innerHTML);
                blockElement.remove();
            }
            if (blockElement.textContent.trim() !== "" && !((_e = blockElement.previousElementSibling) === null || _e === void 0 ? void 0 : _e.querySelector('[data-type="code-block-open-marker"]'))) {
                inputEvent(vditor);
            }
            else {
                if (previousLastElement.getAttribute("data-type") !== "newline") {
                    // https://github.com/Vanessa219/vditor/issues/597
                    range.selectNodeContents(previousLastElement.lastChild);
                    range.collapse(false);
                }
                processAfterRender(vditor);
            }
            event.preventDefault();
            return true;
        }
    }
    return false;
};

// EXTERNAL MODULE: ./src/ts/ui/setContentTheme.ts
var setContentTheme = __webpack_require__(652);
;// CONCATENATED MODULE: ./src/ts/ui/setTheme.ts
var setTheme = function (vditor) {
    if (vditor.options.theme === "dark") {
        vditor.element.classList.add("vditor--dark");
    }
    else {
        vditor.element.classList.remove("vditor--dark");
    }
};

;// CONCATENATED MODULE: ./src/ts/ui/initUI.ts






var initUI = function (vditor) {
    vditor.element.innerHTML = "";
    vditor.element.classList.add("vditor");
    // 支持 RTL
    if (vditor.options.rtl) {
        vditor.element.setAttribute("dir", "rtl");
    }
    setTheme(vditor);
    (0,setContentTheme/* setContentTheme */.Z)(vditor.options.preview.theme.current, vditor.options.preview.theme.path);
    if (typeof vditor.options.height === "number") {
        vditor.element.style.height = vditor.options.height + "px";
    }
    else {
        vditor.element.style.height = vditor.options.height;
    }
    if (typeof vditor.options.minHeight === "number") {
        vditor.element.style.minHeight = vditor.options.minHeight + "px";
    }
    if (typeof vditor.options.width === "number") {
        vditor.element.style.width = vditor.options.width + "px";
    }
    else {
        vditor.element.style.width = vditor.options.width;
    }
    vditor.element.appendChild(vditor.toolbar.element);
    var contentElement = document.createElement("div");
    contentElement.className = "vditor-content";
    if (vditor.options.outline.position === "left") {
        contentElement.appendChild(vditor.outline.element);
    }
    contentElement.appendChild(vditor.wysiwyg.element.parentElement);
    contentElement.appendChild(vditor.sv.element);
    contentElement.appendChild(vditor.ir.element.parentElement);
    contentElement.appendChild(vditor.preview.element);
    if (vditor.toolbar.elements.devtools) {
        contentElement.appendChild(vditor.devtools.element);
    }
    if (vditor.options.outline.position === "right") {
        vditor.outline.element.classList.add("vditor-outline--right");
        contentElement.appendChild(vditor.outline.element);
    }
    if (vditor.upload) {
        contentElement.appendChild(vditor.upload.element);
    }
    if (vditor.options.resize.enable) {
        contentElement.appendChild(vditor.resize.element);
    }
    contentElement.appendChild(vditor.hint.element);
    contentElement.appendChild(vditor.tip.element);
    vditor.element.appendChild(contentElement);
    contentElement.addEventListener("click", function () {
        hidePanel(vditor, ["subToolbar"]);
    });
    if (vditor.toolbar.elements.export) {
        // for export pdf
        vditor.element.insertAdjacentHTML("beforeend", '<iframe id="vditorExportIframe" style="width: 100%;height: 0;border: 0"></iframe>');
    }
    setEditMode(vditor, vditor.options.mode, afterRender(vditor));
    document.execCommand("DefaultParagraphSeparator", false, "p");
    if (navigator.userAgent.indexOf("iPhone") > -1 && typeof window.visualViewport !== "undefined") {
        // https://github.com/Vanessa219/vditor/issues/379
        var pendingUpdate_1 = false;
        var viewportHandler = function (event) {
            if (pendingUpdate_1) {
                return;
            }
            pendingUpdate_1 = true;
            requestAnimationFrame(function () {
                pendingUpdate_1 = false;
                var layoutViewport = vditor.toolbar.element;
                layoutViewport.style.transform = "none";
                if (layoutViewport.getBoundingClientRect().top < 0) {
                    layoutViewport.style.transform = "translate(0, ".concat(-layoutViewport.getBoundingClientRect().top, "px)");
                }
            });
        };
        window.visualViewport.addEventListener("scroll", viewportHandler);
        window.visualViewport.addEventListener("resize", viewportHandler);
    }
};
var setPadding = function (vditor) {
    var minPadding = window.innerWidth <= constants/* Constants.MOBILE_WIDTH */.g.MOBILE_WIDTH ? 10 : 35;
    if (vditor.wysiwyg.element.parentElement.style.display !== "none") {
        var padding = (vditor.wysiwyg.element.parentElement.clientWidth
            - vditor.options.preview.maxWidth) / 2;
        vditor.wysiwyg.element.style.padding = "10px ".concat(Math.max(minPadding, padding), "px");
    }
    if (vditor.ir.element.parentElement.style.display !== "none") {
        var padding = (vditor.ir.element.parentElement.clientWidth
            - vditor.options.preview.maxWidth) / 2;
        vditor.ir.element.style.padding = "10px ".concat(Math.max(minPadding, padding), "px");
    }
    if (vditor.preview.element.style.display !== "block") {
        vditor.toolbar.element.style.paddingLeft = Math.max(5, parseInt(vditor[vditor.currentMode].element.style.paddingLeft || "0", 10) +
            (vditor.options.outline.position === "left" ? vditor.outline.element.offsetWidth : 0)) + "px";
    }
    else {
        vditor.toolbar.element.style.paddingLeft = (5 +
            (vditor.options.outline.position === "left" ? vditor.outline.element.offsetWidth : 0)) + "px";
    }
};
var setTypewriterPosition = function (vditor) {
    if (!vditor.options.typewriterMode) {
        return;
    }
    var height = window.innerHeight;
    if (typeof vditor.options.height === "number") {
        height = vditor.options.height;
        if (typeof vditor.options.minHeight === "number") {
            height = Math.max(height, vditor.options.minHeight);
        }
        height = Math.min(window.innerHeight, height);
    }
    else {
        height = vditor.element.clientHeight;
    }
    if (vditor.element.classList.contains("vditor--fullscreen")) {
        height = window.innerHeight;
    }
    // 由于 Firefox padding-bottom bug，只能使用 :after
    vditor[vditor.currentMode].element.style.setProperty("--editor-bottom", ((height - vditor.toolbar.element.offsetHeight) / 2) + "px");
};
var resizeCb;
function UIUnbindListener() {
    window.removeEventListener("resize", resizeCb);
}
var afterRender = function (vditor) {
    setTypewriterPosition(vditor);
    UIUnbindListener();
    window.addEventListener("resize", resizeCb = function () {
        setPadding(vditor);
        setTypewriterPosition(vditor);
    });
    // set default value
    var initValue = (0,compatibility/* accessLocalStorage */.pK)() && localStorage.getItem(vditor.options.cache.id);
    if (!vditor.options.cache.enable || !initValue) {
        if (vditor.options.value) {
            initValue = vditor.options.value;
        }
        else if (vditor.originalInnerHTML) {
            initValue = vditor.lute.HTML2Md(vditor.originalInnerHTML);
        }
        else if (!vditor.options.cache.enable) {
            initValue = "";
        }
    }
    return initValue || "";
};

;// CONCATENATED MODULE: ./src/ts/ir/highlightToolbarIR.ts





var highlightToolbarIR = function (vditor) {
    clearTimeout(vditor[vditor.currentMode].hlToolbarTimeoutId);
    vditor[vditor.currentMode].hlToolbarTimeoutId = window.setTimeout(function () {
        if (vditor[vditor.currentMode].element.getAttribute("contenteditable") === "false") {
            return;
        }
        if (!(0,selection/* selectIsEditor */.Gb)(vditor[vditor.currentMode].element)) {
            return;
        }
        removeCurrentToolbar(vditor.toolbar.elements, constants/* Constants.EDIT_TOOLBARS */.g.EDIT_TOOLBARS);
        enableToolbar(vditor.toolbar.elements, constants/* Constants.EDIT_TOOLBARS */.g.EDIT_TOOLBARS);
        var range = (0,selection/* getEditorRange */.zh)(vditor);
        var typeElement = range.startContainer;
        if (range.startContainer.nodeType === 3) {
            typeElement = range.startContainer.parentElement;
        }
        if (typeElement.classList.contains("vditor-reset")) {
            typeElement = typeElement.childNodes[range.startOffset];
        }
        var headingElement = vditor.currentMode === "sv" ?
            (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "heading") : (0,hasClosestByHeadings/* hasClosestByHeadings */.W)(typeElement);
        if (headingElement) {
            setCurrentToolbar(vditor.toolbar.elements, ["headings"]);
        }
        var quoteElement = vditor.currentMode === "sv" ? (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "blockquote") :
            (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "BLOCKQUOTE");
        if (quoteElement) {
            setCurrentToolbar(vditor.toolbar.elements, ["quote"]);
        }
        var strongElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "strong");
        if (strongElement) {
            setCurrentToolbar(vditor.toolbar.elements, ["bold"]);
        }
        var emElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "em");
        if (emElement) {
            setCurrentToolbar(vditor.toolbar.elements, ["italic"]);
        }
        var sElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "s");
        if (sElement) {
            setCurrentToolbar(vditor.toolbar.elements, ["strike"]);
        }
        var aElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "a");
        if (aElement) {
            setCurrentToolbar(vditor.toolbar.elements, ["link"]);
        }
        var liElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "LI");
        if (liElement) {
            if (liElement.classList.contains("vditor-task")) {
                setCurrentToolbar(vditor.toolbar.elements, ["check"]);
            }
            else if (liElement.parentElement.tagName === "OL") {
                setCurrentToolbar(vditor.toolbar.elements, ["ordered-list"]);
            }
            else if (liElement.parentElement.tagName === "UL") {
                setCurrentToolbar(vditor.toolbar.elements, ["list"]);
            }
            enableToolbar(vditor.toolbar.elements, ["outdent", "indent"]);
        }
        else {
            disableToolbar(vditor.toolbar.elements, ["outdent", "indent"]);
        }
        var codeBlockElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "code-block");
        if (codeBlockElement) {
            disableToolbar(vditor.toolbar.elements, ["headings", "bold", "italic", "strike", "line", "quote",
                "list", "ordered-list", "check", "code", "inline-code", "upload", "link", "table", "record"]);
            setCurrentToolbar(vditor.toolbar.elements, ["code"]);
        }
        var codeElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "code");
        if (codeElement) {
            disableToolbar(vditor.toolbar.elements, ["headings", "bold", "italic", "strike", "line", "quote",
                "list", "ordered-list", "check", "code", "upload", "link", "table", "record"]);
            setCurrentToolbar(vditor.toolbar.elements, ["inline-code"]);
        }
        var tableElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "table");
        if (tableElement) {
            disableToolbar(vditor.toolbar.elements, ["headings", "list", "ordered-list", "check", "line",
                "quote", "code", "table"]);
        }
    }, 200);
};

;// CONCATENATED MODULE: ./src/ts/wysiwyg/afterRenderEvent.ts


var afterRenderEvent = function (vditor, options) {
    if (options === void 0) { options = {
        enableAddUndoStack: true,
        enableHint: false,
        enableInput: true,
    }; }
    if (options.enableHint) {
        vditor.hint.render(vditor);
    }
    clearTimeout(vditor.wysiwyg.afterRenderTimeoutId);
    vditor.wysiwyg.afterRenderTimeoutId = window.setTimeout(function () {
        if (vditor.wysiwyg.composingLock) {
            return;
        }
        var text = getMarkdown(vditor);
        if (typeof vditor.options.input === "function" && options.enableInput) {
            vditor.options.input(text);
        }
        if (vditor.options.counter.enable) {
            vditor.counter.render(vditor, text);
        }
        if (vditor.options.cache.enable && (0,compatibility/* accessLocalStorage */.pK)()) {
            localStorage.setItem(vditor.options.cache.id, text);
            if (vditor.options.cache.after) {
                vditor.options.cache.after(text);
            }
        }
        if (vditor.devtools) {
            vditor.devtools.renderEchart(vditor);
        }
        if (options.enableAddUndoStack) {
            vditor.undo.addToUndoStack(vditor);
        }
    }, vditor.options.undoDelay);
};

;// CONCATENATED MODULE: ./src/ts/wysiwyg/inlineTag.ts


var previoueIsEmptyA = function (node) {
    var previousNode = node.previousSibling;
    while (previousNode) {
        if (previousNode.nodeType !== 3 && previousNode.tagName === "A" && !previousNode.previousSibling
            && previousNode.innerHTML.replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "" && previousNode.nextSibling) {
            return previousNode;
        }
        previousNode = previousNode.previousSibling;
    }
    return false;
};
var nextIsCode = function (range) {
    var nextNode = range.startContainer.nextSibling;
    while (nextNode && nextNode.textContent === "") {
        nextNode = nextNode.nextSibling;
    }
    if (nextNode && nextNode.nodeType !== 3 && (nextNode.tagName === "CODE" ||
        nextNode.getAttribute("data-type") === "math-inline" ||
        nextNode.getAttribute("data-type") === "html-entity" ||
        nextNode.getAttribute("data-type") === "html-inline")) {
        return true;
    }
    return false;
};
var getNextHTML = function (node) {
    var html = "";
    var nextNode = node.nextSibling;
    while (nextNode) {
        if (nextNode.nodeType === 3) {
            html += nextNode.textContent;
        }
        else {
            html += nextNode.outerHTML;
        }
        nextNode = nextNode.nextSibling;
    }
    return html;
};
var getPreviousHTML = function (node) {
    var html = "";
    var previousNode = node.previousSibling;
    while (previousNode) {
        if (previousNode.nodeType === 3) {
            html = previousNode.textContent + html;
        }
        else {
            html = previousNode.outerHTML + html;
        }
        previousNode = previousNode.previousSibling;
    }
    return html;
};
var getRenderElementNextNode = function (blockCodeElement) {
    var nextNode = blockCodeElement;
    while (nextNode && !nextNode.nextSibling) {
        nextNode = nextNode.parentElement;
    }
    return nextNode.nextSibling;
};
var splitElement = function (range) {
    var previousHTML = getPreviousHTML(range.startContainer);
    var nextHTML = getNextHTML(range.startContainer);
    var text = range.startContainer.textContent;
    var offset = range.startOffset;
    var beforeHTML = "";
    var afterHTML = "";
    if (text.substr(0, offset) !== "" && text.substr(0, offset) !== constants/* Constants.ZWSP */.g.ZWSP || previousHTML) {
        beforeHTML = "".concat(previousHTML).concat(text.substr(0, offset));
    }
    if (text.substr(offset) !== "" && text.substr(offset) !== constants/* Constants.ZWSP */.g.ZWSP || nextHTML) {
        afterHTML = "".concat(text.substr(offset)).concat(nextHTML);
    }
    return {
        afterHTML: afterHTML,
        beforeHTML: beforeHTML,
    };
};
var modifyPre = function (vditor, range) {
    // 没有被块元素包裹
    Array.from(vditor.wysiwyg.element.childNodes).find(function (node) {
        if (node.nodeType === 3) {
            var pElement = document.createElement("p");
            pElement.setAttribute("data-block", "0");
            pElement.textContent = node.textContent;
            // 为空按下 tab 且 tab = '    ' 时，range.startContainer 不为 node
            var cloneRangeOffset = range.startContainer.nodeType === 3 ? range.startOffset : node.textContent.length;
            node.parentNode.insertBefore(pElement, node);
            node.remove();
            range.setStart(pElement.firstChild, Math.min(pElement.firstChild.textContent.length, cloneRangeOffset));
            range.collapse(true);
            (0,selection/* setSelectionFocus */.Hc)(range);
            return true;
        }
        else if (!node.getAttribute("data-block")) {
            if (node.tagName === "P") {
                node.remove();
            }
            else {
                if (node.tagName === "DIV") {
                    range.insertNode(document.createElement("wbr"));
                    // firefox 列表换行产生 div
                    node.outerHTML = "<p data-block=\"0\">".concat(node.innerHTML, "</p>");
                }
                else {
                    if (node.tagName === "BR") {
                        // firefox 空换行产生 BR
                        node.outerHTML = "<p data-block=\"0\">".concat(node.outerHTML, "<wbr></p>");
                    }
                    else {
                        range.insertNode(document.createElement("wbr"));
                        node.outerHTML = "<p data-block=\"0\">".concat(node.outerHTML, "</p>");
                    }
                }
                (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
                range = getSelection().getRangeAt(0);
            }
            return true;
        }
    });
};

;// CONCATENATED MODULE: ./src/ts/wysiwyg/setHeading.ts



var setHeading = function (vditor, tagName) {
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
    if (!blockElement) {
        blockElement = range.startContainer.childNodes[range.startOffset];
    }
    if (!blockElement && vditor.wysiwyg.element.children.length === 0) {
        blockElement = vditor.wysiwyg.element;
    }
    if (blockElement && !blockElement.classList.contains("vditor-wysiwyg__block")) {
        range.insertNode(document.createElement("wbr"));
        // Firefox 需要 trim https://github.com/Vanessa219/vditor/issues/207
        if (blockElement.innerHTML.trim() === "<wbr>") {
            // Firefox 光标对不齐 https://github.com/Vanessa219/vditor/issues/199 1
            blockElement.innerHTML = "<wbr><br>";
        }
        if (blockElement.tagName === "BLOCKQUOTE" || blockElement.classList.contains("vditor-reset")) {
            blockElement.innerHTML = "<".concat(tagName, " data-block=\"0\">").concat(blockElement.innerHTML.trim(), "</").concat(tagName, ">");
        }
        else {
            blockElement.outerHTML = "<".concat(tagName, " data-block=\"0\">").concat(blockElement.innerHTML.trim(), "</").concat(tagName, ">");
        }
        (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
        renderToc(vditor);
    }
};
var removeHeading = function (vditor) {
    var range = getSelection().getRangeAt(0);
    var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
    if (!blockElement) {
        blockElement = range.startContainer.childNodes[range.startOffset];
    }
    if (blockElement) {
        range.insertNode(document.createElement("wbr"));
        blockElement.outerHTML = "<p data-block=\"0\">".concat(blockElement.innerHTML, "</p>");
        (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
    }
    vditor.wysiwyg.popover.style.display = "none";
};

;// CONCATENATED MODULE: ./src/ts/wysiwyg/showCode.ts


var showCode = function (previewElement, vditor, first) {
    if (first === void 0) { first = true; }
    var previousElement = previewElement.previousElementSibling;
    var range = previousElement.ownerDocument.createRange();
    if (previousElement.tagName === "CODE") {
        previousElement.style.display = "inline-block";
        if (first) {
            range.setStart(previousElement.firstChild, 1);
        }
        else {
            range.selectNodeContents(previousElement);
        }
    }
    else {
        previousElement.style.display = "block";
        if (!previousElement.firstChild.firstChild) {
            previousElement.firstChild.appendChild(document.createTextNode(""));
        }
        range.selectNodeContents(previousElement.firstChild);
    }
    if (first) {
        range.collapse(true);
    }
    else {
        range.collapse(false);
    }
    (0,selection/* setSelectionFocus */.Hc)(range);
    if (previewElement.firstElementChild.classList.contains("language-mindmap")) {
        return;
    }
    scrollCenter(vditor);
};

;// CONCATENATED MODULE: ./src/ts/wysiwyg/processKeydown.ts













var wysiwyg_processKeydown_processKeydown = function (vditor, event) {
    // Chrome firefox 触发 compositionend 机制不一致 https://github.com/Vanessa219/vditor/issues/188
    vditor.wysiwyg.composingLock = event.isComposing;
    if (event.isComposing) {
        return false;
    }
    // 添加第一次记录 undo 的光标
    if (event.key.indexOf("Arrow") === -1 && event.key !== "Meta" && event.key !== "Control" && event.key !== "Alt" &&
        event.key !== "Shift" && event.key !== "CapsLock" && event.key !== "Escape" && !/^F\d{1,2}$/.test(event.key)) {
        vditor.undo.recordFirstPosition(vditor, event);
    }
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var startContainer = range.startContainer;
    if (!fixGSKeyBackspace(event, vditor, startContainer)) {
        return false;
    }
    fixCJKPosition(range, vditor, event);
    fixHR(range);
    // 仅处理以下快捷键操作
    if (event.key !== "Enter" && event.key !== "Tab" && event.key !== "Backspace" && event.key.indexOf("Arrow") === -1
        && !(0,compatibility/* isCtrl */.yl)(event) && event.key !== "Escape" && event.key !== "Delete") {
        return false;
    }
    var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(startContainer);
    var pElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "P");
    // md 处理
    if (fixMarkdown(event, vditor, pElement, range)) {
        return true;
    }
    // li
    if (fixList(range, vditor, pElement, event)) {
        return true;
    }
    // table
    if (fixTable(vditor, event, range)) {
        return true;
    }
    // code render
    var codeRenderElement = (0,hasClosest/* hasClosestByClassName */.fb)(startContainer, "vditor-wysiwyg__block");
    if (codeRenderElement) {
        // esc: 退出编辑，仅展示渲染
        if (event.key === "Escape" && codeRenderElement.children.length === 2) {
            vditor.wysiwyg.popover.style.display = "none";
            codeRenderElement.firstElementChild.style.display = "none";
            vditor.wysiwyg.element.blur();
            event.preventDefault();
            return true;
        }
        // alt+enter: 代码块切换到语言 https://github.com/Vanessa219/vditor/issues/54
        if (!(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && event.altKey && event.key === "Enter" &&
            codeRenderElement.getAttribute("data-type") === "code-block") {
            var inputElemment = vditor.wysiwyg.popover.querySelector(".vditor-input");
            inputElemment.focus();
            inputElemment.select();
            event.preventDefault();
            return true;
        }
        if (codeRenderElement.getAttribute("data-block") === "0") {
            if (fixCodeBlock(vditor, event, codeRenderElement.firstElementChild, range)) {
                return true;
            }
            if (insertAfterBlock(vditor, event, range, codeRenderElement.firstElementChild, codeRenderElement)) {
                return true;
            }
            if (codeRenderElement.getAttribute("data-type") !== "yaml-front-matter" &&
                insertBeforeBlock(vditor, event, range, codeRenderElement.firstElementChild, codeRenderElement)) {
                return true;
            }
        }
    }
    // blockquote
    if (fixBlockquote(vditor, range, event, pElement)) {
        return true;
    }
    // 顶层 blockquote
    var topBQElement = (0,hasClosest/* hasTopClosestByTag */.E2)(startContainer, "BLOCKQUOTE");
    if (topBQElement) {
        if (!event.shiftKey && event.altKey && event.key === "Enter") {
            if (!(0,compatibility/* isCtrl */.yl)(event)) {
                // alt+enter: 跳出多层 blockquote 嵌套之后 https://github.com/Vanessa219/vditor/issues/51
                range.setStartAfter(topBQElement);
            }
            else {
                // ctrl+alt+enter: 跳出多层 blockquote 嵌套之前
                range.setStartBefore(topBQElement);
            }
            (0,selection/* setSelectionFocus */.Hc)(range);
            var node = document.createElement("p");
            node.setAttribute("data-block", "0");
            node.innerHTML = "\n";
            range.insertNode(node);
            range.collapse(true);
            (0,selection/* setSelectionFocus */.Hc)(range);
            afterRenderEvent(vditor);
            scrollCenter(vditor);
            event.preventDefault();
            return true;
        }
    }
    // h1-h6
    var headingElement = (0,hasClosestByHeadings/* hasClosestByHeadings */.W)(startContainer);
    if (headingElement) {
        if (headingElement.tagName === "H6" && startContainer.textContent.length === range.startOffset &&
            !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey && event.key === "Enter") {
            // enter: H6 回车解析问题 https://github.com/Vanessa219/vditor/issues/48
            var pTempElement = document.createElement("p");
            pTempElement.textContent = "\n";
            pTempElement.setAttribute("data-block", "0");
            startContainer.parentElement.insertAdjacentElement("afterend", pTempElement);
            range.setStart(pTempElement, 0);
            (0,selection/* setSelectionFocus */.Hc)(range);
            afterRenderEvent(vditor);
            scrollCenter(vditor);
            event.preventDefault();
            return true;
        }
        // enter++: 标题变大
        if (matchHotKey("⌘=", event)) {
            var index = parseInt(headingElement.tagName.substr(1), 10) - 1;
            if (index > 0) {
                setHeading(vditor, "h".concat(index));
                afterRenderEvent(vditor);
            }
            event.preventDefault();
            return true;
        }
        // enter++: 标题变小
        if (matchHotKey("⌘-", event)) {
            var index = parseInt(headingElement.tagName.substr(1), 10) + 1;
            if (index < 7) {
                setHeading(vditor, "h".concat(index));
                afterRenderEvent(vditor);
            }
            event.preventDefault();
            return true;
        }
        if (event.key === "Backspace" && !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey
            && headingElement.textContent.length === 1) {
            // 删除后变为空
            removeHeading(vditor);
        }
    }
    // task list
    if (fixTask(vditor, range, event)) {
        return true;
    }
    // alt+enter
    if (event.altKey && event.key === "Enter" && !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey) {
        // 切换到链接、链接引用、脚注引用弹出的输入框中
        var aElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "A");
        var linRefElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "link-ref");
        var footnoteRefElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "footnotes-ref");
        if (aElement || linRefElement || footnoteRefElement ||
            (headingElement && headingElement.tagName.length === 2)) {
            var inputElement = vditor.wysiwyg.popover.querySelector("input");
            inputElement.focus();
            inputElement.select();
        }
    }
    // 删除有子工具栏的块
    if (removeBlockElement(vditor, event)) {
        return true;
    }
    // 对有子工具栏的块上移
    if (matchHotKey("⇧⌘U", event)) {
        var itemElement = vditor.wysiwyg.popover.querySelector('[data-type="up"]');
        if (itemElement) {
            itemElement.click();
            event.preventDefault();
            return true;
        }
    }
    // 对有子工具栏的块下移
    if (matchHotKey("⇧⌘D", event)) {
        var itemElement = vditor.wysiwyg.popover.querySelector('[data-type="down"]');
        if (itemElement) {
            itemElement.click();
            event.preventDefault();
            return true;
        }
    }
    if (fixTab(vditor, range, event)) {
        return true;
    }
    // shift+enter：软换行，但 table/hr/heading 处理、cell 内换行、block render 换行处理单独写在上面，li & p 使用浏览器默认
    if (!(0,compatibility/* isCtrl */.yl)(event) && event.shiftKey && !event.altKey && event.key === "Enter" &&
        startContainer.parentElement.tagName !== "LI" && startContainer.parentElement.tagName !== "P") {
        if (["STRONG", "STRIKE", "S", "I", "EM", "B"].includes(startContainer.parentElement.tagName)) {
            // 行内元素软换行需继续 https://github.com/Vanessa219/vditor/issues/170
            range.insertNode(document.createTextNode("\n" + constants/* Constants.ZWSP */.g.ZWSP));
        }
        else {
            range.insertNode(document.createTextNode("\n"));
        }
        range.collapse(false);
        (0,selection/* setSelectionFocus */.Hc)(range);
        afterRenderEvent(vditor);
        scrollCenter(vditor);
        event.preventDefault();
        return true;
    }
    // 删除
    if (event.key === "Backspace" && !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey && range.toString() === "") {
        if (fixDelete(vditor, range, event, pElement)) {
            return true;
        }
        if (blockElement) {
            if (blockElement.previousElementSibling
                && blockElement.previousElementSibling.classList.contains("vditor-wysiwyg__block")
                && blockElement.previousElementSibling.getAttribute("data-block") === "0"
                // https://github.com/Vanessa219/vditor/issues/946
                && blockElement.tagName !== "UL" && blockElement.tagName !== "OL") {
                var rangeStart = (0,selection/* getSelectPosition */.im)(blockElement, vditor.wysiwyg.element, range).start;
                if ((rangeStart === 0 && range.startOffset === 0) || // https://github.com/Vanessa219/vditor/issues/894
                    (rangeStart === 1 && blockElement.innerText.startsWith(constants/* Constants.ZWSP */.g.ZWSP))) {
                    // 当前块删除后光标落于代码渲染块上，当前块会被删除，因此需要阻止事件，不能和 keyup 中的代码块处理合并
                    showCode(blockElement.previousElementSibling.lastElementChild, vditor, false);
                    if (blockElement.innerHTML.trim().replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "") {
                        // 当前块为空且不是最后一个时，需要删除
                        blockElement.remove();
                        afterRenderEvent(vditor);
                    }
                    event.preventDefault();
                    return true;
                }
            }
            var rangeStartOffset = range.startOffset;
            if (range.toString() === "" && startContainer.nodeType === 3 &&
                startContainer.textContent.charAt(rangeStartOffset - 2) === "\n" &&
                startContainer.textContent.charAt(rangeStartOffset - 1) !== constants/* Constants.ZWSP */.g.ZWSP
                && ["STRONG", "STRIKE", "S", "I", "EM", "B"].includes(startContainer.parentElement.tagName)) {
                // 保持行内元素软换行需继续的一致性
                startContainer.textContent = startContainer.textContent.substring(0, rangeStartOffset - 1) +
                    constants/* Constants.ZWSP */.g.ZWSP;
                range.setStart(startContainer, rangeStartOffset);
                range.collapse(true);
                afterRenderEvent(vditor);
                event.preventDefault();
                return true;
            }
            // inline code、math、html 行前零宽字符后进行删除
            if (startContainer.textContent === constants/* Constants.ZWSP */.g.ZWSP && range.startOffset === 1
                && !startContainer.previousSibling && nextIsCode(range)) {
                startContainer.textContent = "";
                // 不能返回，其前面为代码渲染块时需进行以下处理：修正光标位于 inline math/html 前，按下删除按钮 code 中内容会被删除
            }
            // 修正光标位于 inline math/html, html-entity 前，按下删除按钮 code 中内容会被删除, 不能返回，还需要进行后续处理
            blockElement.querySelectorAll("span.vditor-wysiwyg__block[data-type='math-inline']").forEach(function (item) {
                item.firstElementChild.style.display = "inline";
                item.lastElementChild.style.display = "none";
            });
            blockElement.querySelectorAll("span.vditor-wysiwyg__block[data-type='html-entity']").forEach(function (item) {
                item.firstElementChild.style.display = "inline";
                item.lastElementChild.style.display = "none";
            });
        }
    }
    if ((0,compatibility/* isFirefox */.vU)() && range.startOffset === 1 && startContainer.textContent.indexOf(constants/* Constants.ZWSP */.g.ZWSP) > -1 &&
        startContainer.previousSibling && startContainer.previousSibling.nodeType !== 3 &&
        startContainer.previousSibling.tagName === "CODE" &&
        (event.key === "Backspace" || event.key === "ArrowLeft")) {
        // https://github.com/Vanessa219/vditor/issues/410
        range.selectNodeContents(startContainer.previousSibling);
        range.collapse(false);
        event.preventDefault();
        return true;
    }
    if (fixFirefoxArrowUpTable(event, blockElement, range)) {
        event.preventDefault();
        return true;
    }
    fixCursorDownInlineMath(range, event.key);
    if (event.key === "ArrowDown") {
        // 光标位于内联数学公式前，按下键无作用
        var nextElement = startContainer.nextSibling;
        if (nextElement && nextElement.nodeType !== 3 && nextElement.getAttribute("data-type") === "math-inline") {
            range.setStartAfter(nextElement);
        }
    }
    if (blockElement && keydownToc(blockElement, vditor, event, range)) {
        event.preventDefault();
        return true;
    }
    return false;
};
var removeBlockElement = function (vditor, event) {
    // 删除有子工具栏的块
    if (matchHotKey("⇧⌘X", event)) {
        var itemElement = vditor.wysiwyg.popover.querySelector('[data-type="remove"]');
        if (itemElement) {
            itemElement.click();
        }
        event.preventDefault();
        return true;
    }
};

;// CONCATENATED MODULE: ./src/ts/wysiwyg/highlightToolbarWYSIWYG.ts
















var highlightToolbarWYSIWYG = function (vditor) {
    clearTimeout(vditor.wysiwyg.hlToolbarTimeoutId);
    vditor.wysiwyg.hlToolbarTimeoutId = window.setTimeout(function () {
        if (vditor.wysiwyg.element.getAttribute("contenteditable") === "false") {
            return;
        }
        if (!(0,selection/* selectIsEditor */.Gb)(vditor.wysiwyg.element)) {
            return;
        }
        removeCurrentToolbar(vditor.toolbar.elements, constants/* Constants.EDIT_TOOLBARS */.g.EDIT_TOOLBARS);
        enableToolbar(vditor.toolbar.elements, constants/* Constants.EDIT_TOOLBARS */.g.EDIT_TOOLBARS);
        var range = getSelection().getRangeAt(0);
        var typeElement = range.startContainer;
        if (range.startContainer.nodeType === 3) {
            typeElement = range.startContainer.parentElement;
        }
        else {
            typeElement = typeElement.childNodes[range.startOffset >= typeElement.childNodes.length
                ? typeElement.childNodes.length - 1
                : range.startOffset];
        }
        var footnotesElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "footnotes-block");
        if (footnotesElement) {
            vditor.wysiwyg.popover.innerHTML = "";
            genClose(footnotesElement, vditor);
            setPopoverPosition(vditor, footnotesElement);
            return;
        }
        // 工具栏高亮和禁用
        var liElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "LI");
        if (liElement) {
            if (liElement.classList.contains("vditor-task")) {
                setCurrentToolbar(vditor.toolbar.elements, ["check"]);
            }
            else if (liElement.parentElement.tagName === "OL") {
                setCurrentToolbar(vditor.toolbar.elements, ["ordered-list"]);
            }
            else if (liElement.parentElement.tagName === "UL") {
                setCurrentToolbar(vditor.toolbar.elements, ["list"]);
            }
            enableToolbar(vditor.toolbar.elements, ["outdent", "indent"]);
        }
        else {
            disableToolbar(vditor.toolbar.elements, ["outdent", "indent"]);
        }
        if ((0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "BLOCKQUOTE")) {
            setCurrentToolbar(vditor.toolbar.elements, ["quote"]);
        }
        if ((0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "B") ||
            (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "STRONG")) {
            setCurrentToolbar(vditor.toolbar.elements, ["bold"]);
        }
        if ((0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "I") ||
            (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "EM")) {
            setCurrentToolbar(vditor.toolbar.elements, ["italic"]);
        }
        if ((0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "STRIKE") ||
            (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "S")) {
            setCurrentToolbar(vditor.toolbar.elements, ["strike"]);
        }
        // comments
        vditor.wysiwyg.element
            .querySelectorAll(".vditor-comment--focus")
            .forEach(function (item) {
            item.classList.remove("vditor-comment--focus");
        });
        var commentElement = (0,hasClosest/* hasClosestByClassName */.fb)(typeElement, "vditor-comment");
        if (commentElement) {
            var ids_1 = commentElement.getAttribute("data-cmtids").split(" ");
            if (ids_1.length > 1 && commentElement.nextSibling.isSameNode(commentElement.nextElementSibling)) {
                var nextIds_1 = commentElement.nextElementSibling
                    .getAttribute("data-cmtids")
                    .split(" ");
                ids_1.find(function (id) {
                    if (nextIds_1.includes(id)) {
                        ids_1 = [id];
                        return true;
                    }
                });
            }
            vditor.wysiwyg.element
                .querySelectorAll(".vditor-comment")
                .forEach(function (item) {
                if (item.getAttribute("data-cmtids").indexOf(ids_1[0]) > -1) {
                    item.classList.add("vditor-comment--focus");
                }
            });
        }
        var aElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "A");
        if (aElement) {
            setCurrentToolbar(vditor.toolbar.elements, ["link"]);
        }
        var tableElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "TABLE");
        var headingElement = (0,hasClosestByHeadings/* hasClosestByHeadings */.W)(typeElement);
        if ((0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "CODE")) {
            if ((0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "PRE")) {
                disableToolbar(vditor.toolbar.elements, [
                    "headings",
                    "bold",
                    "italic",
                    "strike",
                    "line",
                    "quote",
                    "list",
                    "ordered-list",
                    "check",
                    "code",
                    "inline-code",
                    "upload",
                    "link",
                    "table",
                    "record",
                ]);
                setCurrentToolbar(vditor.toolbar.elements, ["code"]);
            }
            else {
                disableToolbar(vditor.toolbar.elements, [
                    "headings",
                    "bold",
                    "italic",
                    "strike",
                    "line",
                    "quote",
                    "list",
                    "ordered-list",
                    "check",
                    "code",
                    "upload",
                    "link",
                    "table",
                    "record",
                ]);
                setCurrentToolbar(vditor.toolbar.elements, ["inline-code"]);
            }
        }
        else if (headingElement) {
            disableToolbar(vditor.toolbar.elements, ["bold"]);
            setCurrentToolbar(vditor.toolbar.elements, ["headings"]);
        }
        else if (tableElement) {
            disableToolbar(vditor.toolbar.elements, ["table"]);
        }
        // toc popover
        var tocElement = (0,hasClosest/* hasClosestByClassName */.fb)(typeElement, "vditor-toc");
        if (tocElement) {
            vditor.wysiwyg.popover.innerHTML = "";
            genClose(tocElement, vditor);
            setPopoverPosition(vditor, tocElement);
            return;
        }
        // quote popover
        var blockquoteElement = (0,hasClosestByHeadings/* hasClosestByTag */.S)(typeElement, "BLOCKQUOTE");
        if (blockquoteElement) {
            vditor.wysiwyg.popover.innerHTML = "";
            genUp(range, blockquoteElement, vditor);
            genDown(range, blockquoteElement, vditor);
            genClose(blockquoteElement, vditor);
            setPopoverPosition(vditor, blockquoteElement);
        }
        // list item popover
        if (liElement) {
            vditor.wysiwyg.popover.innerHTML = "";
            genUp(range, liElement, vditor);
            genDown(range, liElement, vditor);
            genClose(liElement, vditor);
            setPopoverPosition(vditor, liElement);
        }
        // table popover
        if (tableElement) {
            var lang = vditor.options.lang;
            var options = vditor.options;
            vditor.wysiwyg.popover.innerHTML = "";
            var updateTable_1 = function () {
                var oldRow = tableElement.rows.length;
                var oldColumn = tableElement.rows[0].cells.length;
                var row = parseInt(input_1.value, 10) || oldRow;
                var column = parseInt(input2_1.value, 10) || oldColumn;
                if (row === oldRow && oldColumn === column) {
                    return;
                }
                if (oldColumn !== column) {
                    var columnDiff = column - oldColumn;
                    for (var i = 0; i < tableElement.rows.length; i++) {
                        if (columnDiff > 0) {
                            for (var j = 0; j < columnDiff; j++) {
                                if (i === 0) {
                                    tableElement.rows[i].lastElementChild.insertAdjacentHTML("afterend", "<th> </th>");
                                }
                                else {
                                    tableElement.rows[i].lastElementChild.insertAdjacentHTML("afterend", "<td> </td>");
                                }
                            }
                        }
                        else {
                            for (var k = oldColumn - 1; k >= column; k--) {
                                tableElement.rows[i].cells[k].remove();
                            }
                        }
                    }
                }
                if (oldRow !== row) {
                    var rowDiff = row - oldRow;
                    if (rowDiff > 0) {
                        var rowHTML = "<tr>";
                        for (var m = 0; m < column; m++) {
                            rowHTML += "<td> </td>";
                        }
                        for (var l = 0; l < rowDiff; l++) {
                            if (tableElement.querySelector("tbody")) {
                                tableElement
                                    .querySelector("tbody")
                                    .insertAdjacentHTML("beforeend", rowHTML);
                            }
                            else {
                                tableElement
                                    .querySelector("thead")
                                    .insertAdjacentHTML("afterend", rowHTML + "</tr>");
                            }
                        }
                    }
                    else {
                        for (var m = oldRow - 1; m >= row; m--) {
                            tableElement.rows[m].remove();
                            if (tableElement.rows.length === 1) {
                                tableElement.querySelector("tbody").remove();
                            }
                        }
                    }
                }
                if (typeof vditor.options.input === "function") {
                    vditor.options.input(getMarkdown(vditor));
                }
            };
            var setAlign_1 = function (type) {
                setTableAlign(tableElement, type);
                if (type === "right") {
                    left_1.classList.remove("vditor-icon--current");
                    center_1.classList.remove("vditor-icon--current");
                    right_1.classList.add("vditor-icon--current");
                }
                else if (type === "center") {
                    left_1.classList.remove("vditor-icon--current");
                    right_1.classList.remove("vditor-icon--current");
                    center_1.classList.add("vditor-icon--current");
                }
                else {
                    center_1.classList.remove("vditor-icon--current");
                    right_1.classList.remove("vditor-icon--current");
                    left_1.classList.add("vditor-icon--current");
                }
                (0,selection/* setSelectionFocus */.Hc)(range);
                afterRenderEvent(vditor);
            };
            var td = (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "TD");
            var th = (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "TH");
            var alignType = "left";
            if (td) {
                alignType = td.getAttribute("align") || "left";
            }
            else if (th) {
                alignType = th.getAttribute("align") || "center";
            }
            var left_1 = document.createElement("button");
            left_1.setAttribute("type", "button");
            left_1.setAttribute("aria-label", window.VditorI18n.alignLeft + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘L") + ">");
            left_1.setAttribute("data-type", "left");
            left_1.innerHTML =
                '<svg><use xlink:href="#vditor-icon-align-left"></use></svg>';
            left_1.className =
                "vditor-icon vditor-tooltipped vditor-tooltipped__n" +
                    (alignType === "left" ? " vditor-icon--current" : "");
            left_1.onclick = function () {
                setAlign_1("left");
            };
            var center_1 = document.createElement("button");
            center_1.setAttribute("type", "button");
            center_1.setAttribute("aria-label", window.VditorI18n.alignCenter + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘C") + ">");
            center_1.setAttribute("data-type", "center");
            center_1.innerHTML =
                '<svg><use xlink:href="#vditor-icon-align-center"></use></svg>';
            center_1.className =
                "vditor-icon vditor-tooltipped vditor-tooltipped__n" +
                    (alignType === "center" ? " vditor-icon--current" : "");
            center_1.onclick = function () {
                setAlign_1("center");
            };
            var right_1 = document.createElement("button");
            right_1.setAttribute("type", "button");
            right_1.setAttribute("aria-label", window.VditorI18n.alignRight + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘R") + ">");
            right_1.setAttribute("data-type", "right");
            right_1.innerHTML =
                '<svg><use xlink:href="#vditor-icon-align-right"></use></svg>';
            right_1.className =
                "vditor-icon vditor-tooltipped vditor-tooltipped__n" +
                    (alignType === "right" ? " vditor-icon--current" : "");
            right_1.onclick = function () {
                setAlign_1("right");
            };
            var insertRowElement = document.createElement("button");
            insertRowElement.setAttribute("type", "button");
            insertRowElement.setAttribute("aria-label", window.VditorI18n.insertRowBelow + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⌘=") + ">");
            insertRowElement.setAttribute("data-type", "insertRow");
            insertRowElement.innerHTML =
                '<svg><use xlink:href="#vditor-icon-insert-row"></use></svg>';
            insertRowElement.className =
                "vditor-icon vditor-tooltipped vditor-tooltipped__n";
            insertRowElement.onclick = function () {
                var startContainer = getSelection().getRangeAt(0)
                    .startContainer;
                var cellElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TD") ||
                    (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TH");
                if (cellElement) {
                    insertRow(vditor, range, cellElement);
                }
            };
            var insertRowBElement = document.createElement("button");
            insertRowBElement.setAttribute("type", "button");
            insertRowBElement.setAttribute("aria-label", window.VditorI18n.insertRowAbove + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘F") + ">");
            insertRowBElement.setAttribute("data-type", "insertRow");
            insertRowBElement.innerHTML =
                '<svg><use xlink:href="#vditor-icon-insert-rowb"></use></svg>';
            insertRowBElement.className =
                "vditor-icon vditor-tooltipped vditor-tooltipped__n";
            insertRowBElement.onclick = function () {
                var startContainer = getSelection().getRangeAt(0)
                    .startContainer;
                var cellElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TD") ||
                    (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TH");
                if (cellElement) {
                    insertRowAbove(vditor, range, cellElement);
                }
            };
            var insertColumnElement = document.createElement("button");
            insertColumnElement.setAttribute("type", "button");
            insertColumnElement.setAttribute("aria-label", window.VditorI18n.insertColumnRight + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘=") + ">");
            insertColumnElement.setAttribute("data-type", "insertColumn");
            insertColumnElement.innerHTML =
                '<svg><use xlink:href="#vditor-icon-insert-column"></use></svg>';
            insertColumnElement.className =
                "vditor-icon vditor-tooltipped vditor-tooltipped__n";
            insertColumnElement.onclick = function () {
                var startContainer = getSelection().getRangeAt(0)
                    .startContainer;
                var cellElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TD") ||
                    (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TH");
                if (cellElement) {
                    insertColumn(vditor, tableElement, cellElement);
                }
            };
            var insertColumnBElement = document.createElement("button");
            insertColumnBElement.setAttribute("type", "button");
            insertColumnBElement.setAttribute("aria-label", window.VditorI18n.insertColumnLeft + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘G") + ">");
            insertColumnBElement.setAttribute("data-type", "insertColumn");
            insertColumnBElement.innerHTML =
                '<svg><use xlink:href="#vditor-icon-insert-columnb"></use></svg>';
            insertColumnBElement.className =
                "vditor-icon vditor-tooltipped vditor-tooltipped__n";
            insertColumnBElement.onclick = function () {
                var startContainer = getSelection().getRangeAt(0)
                    .startContainer;
                var cellElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TD") ||
                    (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TH");
                if (cellElement) {
                    insertColumn(vditor, tableElement, cellElement, "beforebegin");
                }
            };
            var deleteRowElement = document.createElement("button");
            deleteRowElement.setAttribute("type", "button");
            deleteRowElement.setAttribute("aria-label", window.VditorI18n["delete-row"] + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⌘-") + ">");
            deleteRowElement.setAttribute("data-type", "deleteRow");
            deleteRowElement.innerHTML =
                '<svg><use xlink:href="#vditor-icon-delete-row"></use></svg>';
            deleteRowElement.className =
                "vditor-icon vditor-tooltipped vditor-tooltipped__n";
            deleteRowElement.onclick = function () {
                var startContainer = getSelection().getRangeAt(0)
                    .startContainer;
                var cellElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TD") ||
                    (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TH");
                if (cellElement) {
                    deleteRow(vditor, range, cellElement);
                }
            };
            var deleteColumnElement = document.createElement("button");
            deleteColumnElement.setAttribute("type", "button");
            deleteColumnElement.setAttribute("aria-label", window.VditorI18n["delete-column"] + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘-") + ">");
            deleteColumnElement.setAttribute("data-type", "deleteColumn");
            deleteColumnElement.innerHTML =
                '<svg><use xlink:href="#vditor-icon-delete-column"></use></svg>';
            deleteColumnElement.className =
                "vditor-icon vditor-tooltipped vditor-tooltipped__n";
            deleteColumnElement.onclick = function () {
                var startContainer = getSelection().getRangeAt(0)
                    .startContainer;
                var cellElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TD") ||
                    (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TH");
                if (cellElement) {
                    deleteColumn(vditor, range, tableElement, cellElement);
                }
            };
            var inputWrap = document.createElement("span");
            inputWrap.setAttribute("aria-label", window.VditorI18n.row);
            inputWrap.className = "vditor-tooltipped vditor-tooltipped__n";
            var input_1 = document.createElement("input");
            inputWrap.appendChild(input_1);
            input_1.type = "number";
            input_1.min = "1";
            input_1.className = "vditor-input";
            input_1.style.width = "42px";
            input_1.style.textAlign = "center";
            input_1.setAttribute("placeholder", window.VditorI18n.row);
            input_1.value = tableElement.rows.length.toString();
            input_1.oninput = function () {
                updateTable_1();
            };
            input_1.onkeydown = function (event) {
                if (event.isComposing) {
                    return;
                }
                if (event.key === "Tab") {
                    input2_1.focus();
                    input2_1.select();
                    event.preventDefault();
                    return;
                }
                if (removeBlockElement(vditor, event)) {
                    return;
                }
                if (focusToElement(event, range)) {
                    return;
                }
            };
            var input2Wrap = document.createElement("span");
            input2Wrap.setAttribute("aria-label", window.VditorI18n.column);
            input2Wrap.className = "vditor-tooltipped vditor-tooltipped__n";
            var input2_1 = document.createElement("input");
            input2Wrap.appendChild(input2_1);
            input2_1.type = "number";
            input2_1.min = "1";
            input2_1.className = "vditor-input";
            input2_1.style.width = "42px";
            input2_1.style.textAlign = "center";
            input2_1.setAttribute("placeholder", window.VditorI18n.column);
            input2_1.value = tableElement.rows[0].cells.length.toString();
            input2_1.oninput = function () {
                updateTable_1();
            };
            input2_1.onkeydown = function (event) {
                if (event.isComposing) {
                    return;
                }
                if (event.key === "Tab") {
                    input_1.focus();
                    input_1.select();
                    event.preventDefault();
                    return;
                }
                if (removeBlockElement(vditor, event)) {
                    return;
                }
                if (focusToElement(event, range)) {
                    return;
                }
            };
            genUp(range, tableElement, vditor);
            genDown(range, tableElement, vditor);
            genClose(tableElement, vditor);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", left_1);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", center_1);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", right_1);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", insertRowBElement);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", insertRowElement);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", insertColumnBElement);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", insertColumnElement);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", deleteRowElement);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", deleteColumnElement);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", inputWrap);
            vditor.wysiwyg.popover.insertAdjacentHTML("beforeend", " x ");
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", input2Wrap);
            setPopoverPosition(vditor, tableElement);
        }
        // link ref popover
        var linkRefElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "link-ref");
        if (linkRefElement) {
            genLinkRefPopover(vditor, linkRefElement, range);
        }
        // footnote popover
        var footnotesRefElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-type", "footnotes-ref");
        if (footnotesRefElement) {
            var lang = vditor.options.lang;
            var options = vditor.options;
            vditor.wysiwyg.popover.innerHTML = "";
            var inputWrap = document.createElement("span");
            inputWrap.setAttribute("aria-label", window.VditorI18n.footnoteRef + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⌥Enter") + ">");
            inputWrap.className = "vditor-tooltipped vditor-tooltipped__n";
            var input_2 = document.createElement("input");
            inputWrap.appendChild(input_2);
            input_2.className = "vditor-input";
            input_2.setAttribute("placeholder", window.VditorI18n.footnoteRef + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⌥Enter") + ">");
            input_2.style.width = "120px";
            input_2.value = footnotesRefElement.getAttribute("data-footnotes-label");
            input_2.oninput = function () {
                if (input_2.value.trim() !== "") {
                    footnotesRefElement.setAttribute("data-footnotes-label", input_2.value);
                }
                if (typeof vditor.options.input === "function") {
                    vditor.options.input(getMarkdown(vditor));
                }
            };
            input_2.onkeydown = function (event) {
                if (event.isComposing) {
                    return;
                }
                if (removeBlockElement(vditor, event)) {
                    return;
                }
                if (focusToElement(event, range)) {
                    return;
                }
            };
            genClose(footnotesRefElement, vditor);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", inputWrap);
            setPopoverPosition(vditor, footnotesRefElement);
        }
        // block popover: math-inline, math-block, html-block, html-inline, code-block, html-entity
        var blockRenderElement = (0,hasClosest/* hasClosestByClassName */.fb)(typeElement, "vditor-wysiwyg__block");
        var isBlock = blockRenderElement ? blockRenderElement.getAttribute("data-type").indexOf("block") > -1 : false;
        vditor.wysiwyg.element
            .querySelectorAll(".vditor-wysiwyg__preview")
            .forEach(function (itemElement) {
            if (!blockRenderElement || (blockRenderElement && isBlock && !blockRenderElement.contains(itemElement))) {
                var previousElement = itemElement.previousElementSibling;
                previousElement.style.display = "none";
            }
        });
        if (blockRenderElement && isBlock) {
            vditor.wysiwyg.popover.innerHTML = "";
            genUp(range, blockRenderElement, vditor);
            genDown(range, blockRenderElement, vditor);
            genClose(blockRenderElement, vditor);
            if (blockRenderElement.getAttribute("data-type") === "code-block") {
                var languageWrap = document.createElement("span");
                languageWrap.setAttribute("aria-label", window.VditorI18n.language + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⌥Enter") + ">");
                languageWrap.className = "vditor-tooltipped vditor-tooltipped__n";
                var language_1 = document.createElement("input");
                languageWrap.appendChild(language_1);
                var codeElement_1 = blockRenderElement.firstElementChild.firstElementChild;
                language_1.className = "vditor-input";
                language_1.setAttribute("placeholder", window.VditorI18n.language + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⌥Enter") + ">");
                language_1.value =
                    codeElement_1.className.indexOf("language-") > -1
                        ? codeElement_1.className.split("-")[1].split(" ")[0]
                        : "";
                language_1.oninput = function (e) {
                    if (language_1.value.trim() !== "") {
                        codeElement_1.className = "language-".concat(language_1.value);
                    }
                    else {
                        codeElement_1.className = "";
                        vditor.hint.recentLanguage = "";
                    }
                    if (blockRenderElement.lastElementChild.classList.contains("vditor-wysiwyg__preview")) {
                        blockRenderElement.lastElementChild.innerHTML =
                            blockRenderElement.firstElementChild.innerHTML;
                        processCodeRender(blockRenderElement.lastElementChild, vditor);
                    }
                    afterRenderEvent(vditor);
                    // 当鼠标点选语言时，触发自定义input事件
                    if (e.detail === 1) {
                        // 选择语言后，输入焦点切换到代码输入框
                        range.setStart(codeElement_1.firstChild, 0);
                        range.collapse(true);
                        (0,selection/* setSelectionFocus */.Hc)(range);
                    }
                };
                language_1.onkeydown = function (event) {
                    if (event.isComposing) {
                        return;
                    }
                    if (removeBlockElement(vditor, event)) {
                        return;
                    }
                    if (event.key === "Escape" &&
                        vditor.hint.element.style.display === "block") {
                        vditor.hint.element.style.display = "none";
                        event.preventDefault();
                        return;
                    }
                    vditor.hint.select(event, vditor);
                    focusToElement(event, range);
                };
                language_1.onkeyup = function (event) {
                    if (event.isComposing ||
                        event.key === "Enter" ||
                        event.key === "ArrowUp" ||
                        event.key === "Escape" ||
                        event.key === "ArrowDown") {
                        return;
                    }
                    var matchLangData = [];
                    var key = language_1.value.substring(0, language_1.selectionStart);
                    (vditor.options.preview.hljs.langs || constants/* Constants.CODE_LANGUAGES */.g.CODE_LANGUAGES).forEach(function (keyName) {
                        if (keyName.indexOf(key.toLowerCase()) > -1) {
                            matchLangData.push({
                                html: keyName,
                                value: keyName,
                            });
                        }
                    });
                    vditor.hint.genHTML(matchLangData, key, vditor);
                    event.preventDefault();
                };
                vditor.wysiwyg.popover.insertAdjacentElement("beforeend", languageWrap);
            }
            setPopoverPosition(vditor, blockRenderElement);
        }
        else {
            blockRenderElement = undefined;
        }
        if (headingElement) {
            vditor.wysiwyg.popover.innerHTML = "";
            var inputWrap = document.createElement("span");
            inputWrap.setAttribute("aria-label", "ID" + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⌥Enter") + ">");
            inputWrap.className = "vditor-tooltipped vditor-tooltipped__n";
            var input_3 = document.createElement("input");
            inputWrap.appendChild(input_3);
            input_3.className = "vditor-input";
            input_3.setAttribute("placeholder", "ID" + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⌥Enter") + ">");
            input_3.style.width = "120px";
            input_3.value = headingElement.getAttribute("data-id") || "";
            input_3.oninput = function () {
                headingElement.setAttribute("data-id", input_3.value);
                if (typeof vditor.options.input === "function") {
                    vditor.options.input(getMarkdown(vditor));
                }
            };
            input_3.onkeydown = function (event) {
                if (event.isComposing) {
                    return;
                }
                if (removeBlockElement(vditor, event)) {
                    return;
                }
                if (focusToElement(event, range)) {
                    return;
                }
            };
            genUp(range, headingElement, vditor);
            genDown(range, headingElement, vditor);
            genClose(headingElement, vditor);
            vditor.wysiwyg.popover.insertAdjacentElement("beforeend", inputWrap);
            setPopoverPosition(vditor, headingElement);
        }
        // a popover
        if (aElement) {
            genAPopover(vditor, aElement, range);
        }
        if (!blockquoteElement &&
            !liElement &&
            !tableElement &&
            !blockRenderElement &&
            !aElement &&
            !linkRefElement &&
            !footnotesRefElement &&
            !headingElement &&
            !tocElement) {
            var blockElement = (0,hasClosest/* hasClosestByAttribute */.a1)(typeElement, "data-block", "0");
            if (blockElement &&
                blockElement.parentElement.isEqualNode(vditor.wysiwyg.element)) {
                vditor.wysiwyg.popover.innerHTML = "";
                genUp(range, blockElement, vditor);
                genDown(range, blockElement, vditor);
                genClose(blockElement, vditor);
                setPopoverPosition(vditor, blockElement);
            }
            else {
                vditor.wysiwyg.popover.style.display = "none";
            }
        }
        // 反斜杠特殊处理
        vditor.wysiwyg.element
            .querySelectorAll('span[data-type="backslash"] > span')
            .forEach(function (item) {
            item.style.display = "none";
        });
        var backslashElement = (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-type", "backslash");
        if (backslashElement) {
            backslashElement.querySelector("span").style.display = "inline";
        }
    }, 200);
};
var setPopoverPosition = function (vditor, element) {
    var targetElement = element;
    var tableElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(element, "TABLE");
    if (tableElement) {
        targetElement = tableElement;
    }
    vditor.wysiwyg.popover.style.left = "0";
    vditor.wysiwyg.popover.style.display = "block";
    vditor.wysiwyg.popover.style.top =
        Math.max(-8, targetElement.offsetTop - 21 - vditor.wysiwyg.element.scrollTop) + "px";
    vditor.wysiwyg.popover.style.left =
        Math.min(targetElement.offsetLeft, vditor.wysiwyg.element.clientWidth - vditor.wysiwyg.popover.clientWidth) + "px";
    vditor.wysiwyg.popover.setAttribute("data-top", (targetElement.offsetTop - 21).toString());
};
var genLinkRefPopover = function (vditor, linkRefElement, range) {
    if (range === void 0) { range = getSelection().getRangeAt(0); }
    vditor.wysiwyg.popover.innerHTML = "";
    var updateLinkRef = function () {
        if (input.value.trim() !== "") {
            if (linkRefElement.tagName === "IMG") {
                linkRefElement.setAttribute("alt", input.value);
            }
            else {
                linkRefElement.textContent = input.value;
            }
        }
        // data-link-label
        if (input1.value.trim() !== "") {
            linkRefElement.setAttribute("data-link-label", input1.value);
        }
        if (typeof vditor.options.input === "function") {
            vditor.options.input(getMarkdown(vditor));
        }
    };
    var inputWrap = document.createElement("span");
    inputWrap.setAttribute("aria-label", window.VditorI18n.textIsNotEmpty);
    inputWrap.className = "vditor-tooltipped vditor-tooltipped__n";
    var input = document.createElement("input");
    inputWrap.appendChild(input);
    input.className = "vditor-input";
    input.setAttribute("placeholder", window.VditorI18n.textIsNotEmpty);
    input.style.width = "120px";
    input.value =
        linkRefElement.getAttribute("alt") || linkRefElement.textContent;
    input.oninput = function () {
        updateLinkRef();
    };
    input.onkeydown = function (event) {
        if (removeBlockElement(vditor, event)) {
            return;
        }
        if (focusToElement(event, range)) {
            return;
        }
        linkHotkey(vditor, linkRefElement, event, input1);
    };
    var input1Wrap = document.createElement("span");
    input1Wrap.setAttribute("aria-label", window.VditorI18n.linkRef);
    input1Wrap.className = "vditor-tooltipped vditor-tooltipped__n";
    var input1 = document.createElement("input");
    input1Wrap.appendChild(input1);
    input1.className = "vditor-input";
    input1.setAttribute("placeholder", window.VditorI18n.linkRef);
    input1.value = linkRefElement.getAttribute("data-link-label");
    input1.oninput = function () {
        updateLinkRef();
    };
    input1.onkeydown = function (event) {
        if (removeBlockElement(vditor, event)) {
            return;
        }
        if (focusToElement(event, range)) {
            return;
        }
        linkHotkey(vditor, linkRefElement, event, input);
    };
    genClose(linkRefElement, vditor);
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", inputWrap);
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", input1Wrap);
    setPopoverPosition(vditor, linkRefElement);
};
var genUp = function (range, element, vditor) {
    var previousElement = element.previousElementSibling;
    if (!previousElement ||
        (!element.parentElement.isEqualNode(vditor.wysiwyg.element) &&
            element.tagName !== "LI")) {
        return;
    }
    var upElement = document.createElement("button");
    upElement.setAttribute("type", "button");
    upElement.setAttribute("data-type", "up");
    upElement.setAttribute("aria-label", window.VditorI18n.up + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘U") + ">");
    upElement.innerHTML = '<svg><use xlink:href="#vditor-icon-up"></use></svg>';
    upElement.className = "vditor-icon vditor-tooltipped vditor-tooltipped__n";
    upElement.onclick = function () {
        range.insertNode(document.createElement("wbr"));
        previousElement.insertAdjacentElement("beforebegin", element);
        (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
        afterRenderEvent(vditor);
        highlightToolbarWYSIWYG(vditor);
        scrollCenter(vditor);
    };
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", upElement);
};
var genDown = function (range, element, vditor) {
    var nextElement = element.nextElementSibling;
    if (!nextElement ||
        (!element.parentElement.isEqualNode(vditor.wysiwyg.element) &&
            element.tagName !== "LI")) {
        return;
    }
    var downElement = document.createElement("button");
    downElement.setAttribute("type", "button");
    downElement.setAttribute("data-type", "down");
    downElement.setAttribute("aria-label", window.VditorI18n.down + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘D") + ">");
    downElement.innerHTML =
        '<svg><use xlink:href="#vditor-icon-down"></use></svg>';
    downElement.className =
        "vditor-icon vditor-tooltipped vditor-tooltipped__n";
    downElement.onclick = function () {
        range.insertNode(document.createElement("wbr"));
        nextElement.insertAdjacentElement("afterend", element);
        (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
        afterRenderEvent(vditor);
        highlightToolbarWYSIWYG(vditor);
        scrollCenter(vditor);
    };
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", downElement);
};
var genClose = function (element, vditor) {
    var close = document.createElement("button");
    close.setAttribute("type", "button");
    close.setAttribute("data-type", "remove");
    close.setAttribute("aria-label", window.VditorI18n.remove + "<" + (0,compatibility/* updateHotkeyTip */.ns)("⇧⌘X") + ">");
    close.innerHTML =
        '<svg><use xlink:href="#vditor-icon-trashcan"></use></svg>';
    close.className = "vditor-icon vditor-tooltipped vditor-tooltipped__n";
    close.onclick = function () {
        var range = (0,selection/* getEditorRange */.zh)(vditor);
        range.setStartAfter(element);
        (0,selection/* setSelectionFocus */.Hc)(range);
        element.remove();
        afterRenderEvent(vditor);
        highlightToolbarWYSIWYG(vditor);
        if (["H1", "H2", "H3", "H4", "H5", "H6"].includes(element.tagName)) {
            renderToc(vditor);
        }
    };
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", close);
};
var linkHotkey = function (vditor, element, event, nextInputElement) {
    if (event.isComposing) {
        return;
    }
    if (event.key === "Tab") {
        nextInputElement.focus();
        nextInputElement.select();
        event.preventDefault();
        return;
    }
    if (!(0,compatibility/* isCtrl */.yl)(event) &&
        !event.shiftKey &&
        event.altKey &&
        event.key === "Enter") {
        var range = (0,selection/* getEditorRange */.zh)(vditor);
        // firefox 不会打断 link https://github.com/Vanessa219/vditor/issues/193
        element.insertAdjacentHTML("afterend", constants/* Constants.ZWSP */.g.ZWSP);
        range.setStartAfter(element.nextSibling);
        range.collapse(true);
        (0,selection/* setSelectionFocus */.Hc)(range);
        event.preventDefault();
    }
};
var genAPopover = function (vditor, aElement, range) {
    vditor.wysiwyg.popover.innerHTML = "";
    var updateA = function () {
        if (input.value.trim() !== "") {
            aElement.innerHTML = input.value;
        }
        aElement.setAttribute("href", input1.value);
        aElement.setAttribute("title", input2.value);
        afterRenderEvent(vditor);
    };
    aElement.querySelectorAll("[data-marker]").forEach(function (item) {
        item.removeAttribute("data-marker");
    });
    var inputWrap = document.createElement("span");
    inputWrap.setAttribute("aria-label", window.VditorI18n.textIsNotEmpty);
    inputWrap.className = "vditor-tooltipped vditor-tooltipped__n";
    var input = document.createElement("input");
    inputWrap.appendChild(input);
    input.className = "vditor-input";
    input.setAttribute("placeholder", window.VditorI18n.textIsNotEmpty);
    input.style.width = "120px";
    input.value = aElement.innerHTML || "";
    input.oninput = function () {
        updateA();
    };
    input.onkeydown = function (event) {
        if (removeBlockElement(vditor, event)) {
            return;
        }
        if (focusToElement(event, range)) {
            return;
        }
        linkHotkey(vditor, aElement, event, input1);
    };
    var input1Wrap = document.createElement("span");
    input1Wrap.setAttribute("aria-label", window.VditorI18n.link);
    input1Wrap.className = "vditor-tooltipped vditor-tooltipped__n";
    var input1 = document.createElement("input");
    input1Wrap.appendChild(input1);
    input1.className = "vditor-input";
    input1.setAttribute("placeholder", window.VditorI18n.link);
    input1.value = aElement.getAttribute("href") || "";
    input1.oninput = function () {
        updateA();
    };
    input1.onkeydown = function (event) {
        if (removeBlockElement(vditor, event)) {
            return;
        }
        if (focusToElement(event, range)) {
            return;
        }
        linkHotkey(vditor, aElement, event, input2);
    };
    var input2Wrap = document.createElement("span");
    input2Wrap.setAttribute("aria-label", window.VditorI18n.tooltipText);
    input2Wrap.className = "vditor-tooltipped vditor-tooltipped__n";
    var input2 = document.createElement("input");
    input2Wrap.appendChild(input2);
    input2.className = "vditor-input";
    input2.setAttribute("placeholder", window.VditorI18n.tooltipText);
    input2.style.width = "60px";
    input2.value = aElement.getAttribute("title") || "";
    input2.oninput = function () {
        updateA();
    };
    input2.onkeydown = function (event) {
        if (removeBlockElement(vditor, event)) {
            return;
        }
        if (focusToElement(event, range)) {
            return;
        }
        linkHotkey(vditor, aElement, event, input);
    };
    genClose(aElement, vditor);
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", inputWrap);
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", input1Wrap);
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", input2Wrap);
    setPopoverPosition(vditor, aElement);
};
var genImagePopover = function (event, vditor) {
    var imgElement = event.target;
    vditor.wysiwyg.popover.innerHTML = "";
    var updateImg = function () {
        imgElement.setAttribute("src", inputElement.value);
        imgElement.setAttribute("alt", alt.value);
        imgElement.setAttribute("title", title.value);
        if (typeof vditor.options.input === "function") {
            vditor.options.input(getMarkdown(vditor));
        }
    };
    var inputWrap = document.createElement("span");
    inputWrap.setAttribute("aria-label", window.VditorI18n.imageURL);
    inputWrap.className = "vditor-tooltipped vditor-tooltipped__n";
    var inputElement = document.createElement("input");
    inputWrap.appendChild(inputElement);
    inputElement.className = "vditor-input";
    inputElement.setAttribute("placeholder", window.VditorI18n.imageURL);
    inputElement.value = imgElement.getAttribute("src") || "";
    inputElement.oninput = function () {
        updateImg();
    };
    inputElement.onkeydown = function (elementEvent) {
        removeBlockElement(vditor, elementEvent);
    };
    var altWrap = document.createElement("span");
    altWrap.setAttribute("aria-label", window.VditorI18n.alternateText);
    altWrap.className = "vditor-tooltipped vditor-tooltipped__n";
    var alt = document.createElement("input");
    altWrap.appendChild(alt);
    alt.className = "vditor-input";
    alt.setAttribute("placeholder", window.VditorI18n.alternateText);
    alt.style.width = "52px";
    alt.value = imgElement.getAttribute("alt") || "";
    alt.oninput = function () {
        updateImg();
    };
    alt.onkeydown = function (elementEvent) {
        removeBlockElement(vditor, elementEvent);
    };
    var titleWrap = document.createElement("span");
    titleWrap.setAttribute("aria-label", window.VditorI18n.title);
    titleWrap.className = "vditor-tooltipped vditor-tooltipped__n";
    var title = document.createElement("input");
    titleWrap.appendChild(title);
    title.className = "vditor-input";
    title.setAttribute("placeholder", window.VditorI18n.title);
    title.value = imgElement.getAttribute("title") || "";
    title.oninput = function () {
        updateImg();
    };
    title.onkeydown = function (elementEvent) {
        removeBlockElement(vditor, elementEvent);
    };
    genClose(imgElement, vditor);
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", inputWrap);
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", altWrap);
    vditor.wysiwyg.popover.insertAdjacentElement("beforeend", titleWrap);
    setPopoverPosition(vditor, imgElement);
};
var focusToElement = function (event, range) {
    if ((!(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && event.key === "Enter") || event.key === "Escape") {
        if (range) {
            (0,selection/* setSelectionFocus */.Hc)(range);
        }
        event.preventDefault();
        event.stopPropagation();
        return true;
    }
};

;// CONCATENATED MODULE: ./src/ts/util/highlightToolbar.ts


var highlightToolbar = function (vditor) {
    if (vditor.currentMode === "wysiwyg") {
        highlightToolbarWYSIWYG(vditor);
    }
    else if (vditor.currentMode === "ir") {
        highlightToolbarIR(vditor);
    }
};

;// CONCATENATED MODULE: ./src/ts/wysiwyg/renderDomByMd.ts


var renderDomByMd = function (vditor, md, options) {
    if (options === void 0) { options = {
        enableAddUndoStack: true,
        enableHint: false,
        enableInput: true,
    }; }
    var editorElement = vditor.wysiwyg.element;
    editorElement.innerHTML = vditor.lute.Md2VditorDOM(md);
    editorElement.querySelectorAll(".vditor-wysiwyg__preview[data-render='2']").forEach(function (item) {
        processCodeRender(item, vditor);
        item.previousElementSibling.setAttribute("style", "display:none");
    });
    afterRenderEvent(vditor, options);
};

;// CONCATENATED MODULE: ./src/ts/wysiwyg/toolbarEvent.ts









var cancelBES = function (range, vditor, commandName) {
    var element = range.startContainer.parentElement;
    var jump = false;
    var lastTagName = "";
    var lastEndTagName = "";
    var splitHTML = splitElement(range);
    var lastBeforeHTML = splitHTML.beforeHTML;
    var lastAfterHTML = splitHTML.afterHTML;
    while (element && !jump) {
        var tagName = element.tagName;
        if (tagName === "STRIKE") {
            tagName = "S";
        }
        if (tagName === "I") {
            tagName = "EM";
        }
        if (tagName === "B") {
            tagName = "STRONG";
        }
        if (tagName === "S" || tagName === "STRONG" || tagName === "EM") {
            var insertHTML = "";
            var previousHTML = "";
            var nextHTML = "";
            if (element.parentElement.getAttribute("data-block") !== "0") {
                previousHTML = getPreviousHTML(element);
                nextHTML = getNextHTML(element);
            }
            if (lastBeforeHTML || previousHTML) {
                insertHTML = "".concat(previousHTML, "<").concat(tagName, ">").concat(lastBeforeHTML, "</").concat(tagName, ">");
                lastBeforeHTML = insertHTML;
            }
            if ((commandName === "bold" && tagName === "STRONG") ||
                (commandName === "italic" && tagName === "EM") ||
                (commandName === "strikeThrough" && tagName === "S")) {
                // 取消
                insertHTML += "".concat(lastTagName).concat(constants/* Constants.ZWSP */.g.ZWSP, "<wbr>").concat(lastEndTagName);
                jump = true;
            }
            if (lastAfterHTML || nextHTML) {
                lastAfterHTML = "<".concat(tagName, ">").concat(lastAfterHTML, "</").concat(tagName, ">").concat(nextHTML);
                insertHTML += lastAfterHTML;
            }
            if (element.parentElement.getAttribute("data-block") !== "0") {
                element = element.parentElement;
                element.innerHTML = insertHTML;
            }
            else {
                element.outerHTML = insertHTML;
                element = element.parentElement;
            }
            lastTagName = "<".concat(tagName, ">") + lastTagName;
            lastEndTagName = "</".concat(tagName, ">") + lastEndTagName;
        }
        else {
            jump = true;
        }
    }
    (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
};
var toolbarEvent = function (vditor, actionBtn, event) {
    if (vditor.wysiwyg.composingLock // Mac Chrome 中韩文结束会出发此事件，导致重复末尾字符 https://github.com/Vanessa219/vditor/issues/188
        && event instanceof CustomEvent // 点击按钮应忽略输入法 https://github.com/Vanessa219/vditor/issues/473
    ) {
        return;
    }
    var useHighlight = true;
    var useRender = true;
    if (vditor.wysiwyg.element.querySelector("wbr")) {
        vditor.wysiwyg.element.querySelector("wbr").remove();
    }
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var commandName = actionBtn.getAttribute("data-type");
    // 移除
    if (actionBtn.classList.contains("vditor-menu--current")) {
        if (commandName === "strike") {
            commandName = "strikeThrough";
        }
        if (commandName === "quote") {
            var quoteElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "BLOCKQUOTE");
            if (!quoteElement) {
                quoteElement = range.startContainer.childNodes[range.startOffset];
            }
            if (quoteElement) {
                useHighlight = false;
                actionBtn.classList.remove("vditor-menu--current");
                range.insertNode(document.createElement("wbr"));
                quoteElement.outerHTML = quoteElement.innerHTML.trim() === "" ?
                    "<p data-block=\"0\">".concat(quoteElement.innerHTML, "</p>") : quoteElement.innerHTML;
                (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
            }
        }
        else if (commandName === "inline-code") {
            var inlineCodeElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "CODE");
            if (!inlineCodeElement) {
                inlineCodeElement = range.startContainer.childNodes[range.startOffset];
            }
            if (inlineCodeElement) {
                inlineCodeElement.outerHTML = inlineCodeElement.innerHTML.replace(constants/* Constants.ZWSP */.g.ZWSP, "") + "<wbr>";
                (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
            }
        }
        else if (commandName === "link") {
            if (!range.collapsed) {
                document.execCommand("unlink", false, "");
            }
            else {
                range.selectNode(range.startContainer.parentElement);
                document.execCommand("unlink", false, "");
            }
        }
        else if (commandName === "check" || commandName === "list" || commandName === "ordered-list") {
            listToggle(vditor, range, commandName);
            (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
            useHighlight = false;
            actionBtn.classList.remove("vditor-menu--current");
        }
        else {
            // bold, italic, strike
            useHighlight = false;
            actionBtn.classList.remove("vditor-menu--current");
            if (range.toString() === "") {
                cancelBES(range, vditor, commandName);
            }
            else {
                document.execCommand(commandName, false, "");
            }
        }
    }
    else {
        // 添加
        if (vditor.wysiwyg.element.childNodes.length === 0) {
            vditor.wysiwyg.element.innerHTML = '<p data-block="0"><wbr></p>';
            (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
        }
        var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
        if (commandName === "quote") {
            if (!blockElement) {
                blockElement = range.startContainer.childNodes[range.startOffset];
            }
            if (blockElement) {
                useHighlight = false;
                actionBtn.classList.add("vditor-menu--current");
                range.insertNode(document.createElement("wbr"));
                var liElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "LI");
                // li 中软换行
                if (liElement && blockElement.contains(liElement)) {
                    liElement.innerHTML = "<blockquote data-block=\"0\">".concat(liElement.innerHTML, "</blockquote>");
                }
                else {
                    blockElement.outerHTML = "<blockquote data-block=\"0\">".concat(blockElement.outerHTML, "</blockquote>");
                }
                (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
            }
        }
        else if (commandName === "check" || commandName === "list" || commandName === "ordered-list") {
            listToggle(vditor, range, commandName, false);
            (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
            useHighlight = false;
            removeCurrentToolbar(vditor.toolbar.elements, ["check", "list", "ordered-list"]);
            actionBtn.classList.add("vditor-menu--current");
        }
        else if (commandName === "inline-code") {
            if (range.toString() === "") {
                var node = document.createElement("code");
                node.textContent = constants/* Constants.ZWSP */.g.ZWSP;
                range.insertNode(node);
                range.setStart(node.firstChild, 1);
                range.collapse(true);
                (0,selection/* setSelectionFocus */.Hc)(range);
            }
            else if (range.startContainer.nodeType === 3) {
                var node = document.createElement("code");
                range.surroundContents(node);
                range.insertNode(node);
                (0,selection/* setSelectionFocus */.Hc)(range);
            }
            actionBtn.classList.add("vditor-menu--current");
        }
        else if (commandName === "code") {
            var node = document.createElement("div");
            node.className = "vditor-wysiwyg__block";
            node.setAttribute("data-type", "code-block");
            node.setAttribute("data-block", "0");
            node.setAttribute("data-marker", "```");
            if (range.toString() === "") {
                node.innerHTML = "<pre><code><wbr>\n</code></pre>";
            }
            else {
                node.innerHTML = "<pre><code>".concat(range.toString(), "<wbr></code></pre>");
                range.deleteContents();
            }
            range.insertNode(node);
            if (blockElement) {
                blockElement.outerHTML = vditor.lute.SpinVditorDOM(blockElement.outerHTML);
            }
            (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
            vditor.wysiwyg.element.querySelectorAll(".vditor-wysiwyg__preview[data-render='2']").forEach(function (item) {
                processCodeRender(item, vditor);
            });
            actionBtn.classList.add("vditor-menu--disabled");
        }
        else if (commandName === "link") {
            if (range.toString() === "") {
                var aElement = document.createElement("a");
                aElement.innerText = constants/* Constants.ZWSP */.g.ZWSP;
                range.insertNode(aElement);
                range.setStart(aElement.firstChild, 1);
                range.collapse(true);
                genAPopover(vditor, aElement, range);
                var textInputElement = vditor.wysiwyg.popover.querySelector("input");
                textInputElement.value = "";
                textInputElement.focus();
                useRender = false;
            }
            else {
                var node = document.createElement("a");
                node.setAttribute("href", "");
                node.innerHTML = range.toString();
                range.surroundContents(node);
                range.insertNode(node);
                (0,selection/* setSelectionFocus */.Hc)(range);
                genAPopover(vditor, node, range);
                var textInputElements = vditor.wysiwyg.popover.querySelectorAll("input");
                textInputElements[0].value = node.innerText;
                textInputElements[1].focus();
            }
            useHighlight = false;
            actionBtn.classList.add("vditor-menu--current");
        }
        else if (commandName === "table") {
            var tableHTML_1 = "<table data-block=\"0\"><thead><tr><th>col1<wbr></th><th>col2</th><th>col3</th></tr></thead><tbody><tr><td> </td><td> </td><td> </td></tr><tr><td> </td><td> </td><td> </td></tr></tbody></table>";
            if (range.toString().trim() === "") {
                if (blockElement && blockElement.innerHTML.trim().replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "") {
                    blockElement.outerHTML = tableHTML_1;
                }
                else {
                    document.execCommand("insertHTML", false, tableHTML_1);
                }
                range.selectNode(vditor.wysiwyg.element.querySelector("wbr").previousSibling);
                vditor.wysiwyg.element.querySelector("wbr").remove();
                (0,selection/* setSelectionFocus */.Hc)(range);
            }
            else {
                tableHTML_1 = "<table data-block=\"0\"><thead><tr>";
                var tableText = range.toString().split("\n");
                var delimiter_1 = tableText[0].split(",").length > tableText[0].split("\t").length ? "," : "\t";
                tableText.forEach(function (rows, index) {
                    if (index === 0) {
                        rows.split(delimiter_1).forEach(function (header, subIndex) {
                            if (subIndex === 0) {
                                tableHTML_1 += "<th>".concat(header, "<wbr></th>");
                            }
                            else {
                                tableHTML_1 += "<th>".concat(header, "</th>");
                            }
                        });
                        tableHTML_1 += "</tr></thead>";
                    }
                    else {
                        if (index === 1) {
                            tableHTML_1 += "<tbody><tr>";
                        }
                        else {
                            tableHTML_1 += "<tr>";
                        }
                        rows.split(delimiter_1).forEach(function (cell) {
                            tableHTML_1 += "<td>".concat(cell, "</td>");
                        });
                        tableHTML_1 += "</tr>";
                    }
                });
                tableHTML_1 += "</tbody></table>";
                document.execCommand("insertHTML", false, tableHTML_1);
                (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
            }
            useHighlight = false;
            actionBtn.classList.add("vditor-menu--disabled");
        }
        else if (commandName === "line") {
            if (blockElement) {
                var hrHTML = '<hr data-block="0"><p data-block="0"><wbr>\n</p>';
                if (blockElement.innerHTML.trim() === "") {
                    blockElement.outerHTML = hrHTML;
                }
                else {
                    blockElement.insertAdjacentHTML("afterend", hrHTML);
                }
                (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
            }
        }
        else {
            // bold, italic, strike
            useHighlight = false;
            actionBtn.classList.add("vditor-menu--current");
            if (commandName === "strike") {
                commandName = "strikeThrough";
            }
            if (range.toString() === "" && (commandName === "bold" || commandName === "italic" || commandName === "strikeThrough")) {
                var tagName = "strong";
                if (commandName === "italic") {
                    tagName = "em";
                }
                else if (commandName === "strikeThrough") {
                    tagName = "s";
                }
                var node = document.createElement(tagName);
                node.textContent = constants/* Constants.ZWSP */.g.ZWSP;
                range.insertNode(node);
                if (node.previousSibling && node.previousSibling.textContent === constants/* Constants.ZWSP */.g.ZWSP) {
                    // 移除多层嵌套中的 zwsp
                    node.previousSibling.textContent = "";
                }
                range.setStart(node.firstChild, 1);
                range.collapse(true);
                (0,selection/* setSelectionFocus */.Hc)(range);
            }
            else {
                document.execCommand(commandName, false, "");
            }
        }
    }
    if (useHighlight) {
        highlightToolbarWYSIWYG(vditor);
    }
    if (useRender) {
        afterRenderEvent(vditor);
    }
};

;// CONCATENATED MODULE: ./src/ts/toolbar/MenuItem.ts






var MenuItem = /** @class */ (function () {
    function MenuItem(vditor, menuItem) {
        var _a;
        var _this = this;
        this.element = document.createElement("div");
        if (menuItem.className) {
            (_a = this.element.classList).add.apply(_a, menuItem.className.split(" "));
        }
        var hotkey = menuItem.hotkey ? " <".concat((0,compatibility/* updateHotkeyTip */.ns)(menuItem.hotkey), ">") : "";
        if (menuItem.level === 2) {
            hotkey = menuItem.hotkey ? " &lt;".concat((0,compatibility/* updateHotkeyTip */.ns)(menuItem.hotkey), "&gt;") : "";
        }
        var tip = menuItem.tip ? menuItem.tip + hotkey : "".concat(window.VditorI18n[menuItem.name]).concat(hotkey);
        var tagName = menuItem.name === "upload" ? "div" : "button";
        if (menuItem.level === 2) {
            this.element.innerHTML = "<".concat(tagName, " data-type=\"").concat(menuItem.name, "\">").concat(tip, "</").concat(tagName, ">");
        }
        else {
            this.element.classList.add("vditor-toolbar__item");
            var iconElement = document.createElement(tagName);
            iconElement.setAttribute("data-type", menuItem.name);
            iconElement.className = "vditor-tooltipped vditor-tooltipped__".concat(menuItem.tipPosition);
            iconElement.setAttribute("aria-label", tip);
            iconElement.innerHTML = menuItem.icon;
            this.element.appendChild(iconElement);
        }
        if (!menuItem.prefix) {
            return;
        }
        this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            if (vditor.currentMode === "wysiwyg") {
                toolbarEvent(vditor, _this.element.children[0], event);
            }
            else if (vditor.currentMode === "ir") {
                process_processToolbar(vditor, _this.element.children[0], menuItem.prefix || "", menuItem.suffix || "");
            }
            else {
                processToolbar(vditor, _this.element.children[0], menuItem.prefix || "", menuItem.suffix || "");
            }
        });
    }
    return MenuItem;
}());


;// CONCATENATED MODULE: ./src/ts/toolbar/EditMode.ts
var __extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();














var setEditMode = function (vditor, type, event) {
    var markdownText;
    if (typeof event !== "string") {
        hidePanel(vditor, ["subToolbar", "hint"]);
        event.preventDefault();
        markdownText = getMarkdown(vditor);
    }
    else {
        markdownText = event;
    }
    if (vditor.currentMode === type && typeof event !== "string") {
        return;
    }
    if (vditor.devtools) {
        vditor.devtools.renderEchart(vditor);
    }
    if (vditor.options.preview.mode === "both" && type === "sv") {
        vditor.preview.element.style.display = "block";
    }
    else {
        vditor.preview.element.style.display = "none";
    }
    enableToolbar(vditor.toolbar.elements, constants/* Constants.EDIT_TOOLBARS */.g.EDIT_TOOLBARS);
    removeCurrentToolbar(vditor.toolbar.elements, constants/* Constants.EDIT_TOOLBARS */.g.EDIT_TOOLBARS);
    disableToolbar(vditor.toolbar.elements, ["outdent", "indent"]);
    if (type === "ir") {
        hideToolbar(vditor.toolbar.elements, ["both"]);
        showToolbar(vditor.toolbar.elements, ["outdent", "indent", "outline", "insert-before", "insert-after"]);
        vditor.sv.element.style.display = "none";
        vditor.wysiwyg.element.parentElement.style.display = "none";
        vditor.ir.element.parentElement.style.display = "block";
        vditor.lute.SetVditorIR(true);
        vditor.lute.SetVditorWYSIWYG(false);
        vditor.lute.SetVditorSV(false);
        vditor.currentMode = "ir";
        vditor.ir.element.innerHTML = vditor.lute.Md2VditorIRDOM(markdownText);
        process_processAfterRender(vditor, {
            enableAddUndoStack: true,
            enableHint: false,
            enableInput: false,
        });
        setPadding(vditor);
        vditor.ir.element.querySelectorAll(".vditor-ir__preview[data-render='2']").forEach(function (item) {
            processCodeRender(item, vditor);
        });
        vditor.ir.element.querySelectorAll(".vditor-toc").forEach(function (item) {
            (0,mathRender/* mathRender */.H)(item, {
                cdn: vditor.options.cdn,
                math: vditor.options.preview.math,
            });
        });
    }
    else if (type === "wysiwyg") {
        hideToolbar(vditor.toolbar.elements, ["both"]);
        showToolbar(vditor.toolbar.elements, ["outdent", "indent", "outline", "insert-before", "insert-after"]);
        vditor.sv.element.style.display = "none";
        vditor.wysiwyg.element.parentElement.style.display = "block";
        vditor.ir.element.parentElement.style.display = "none";
        vditor.lute.SetVditorIR(false);
        vditor.lute.SetVditorWYSIWYG(true);
        vditor.lute.SetVditorSV(false);
        vditor.currentMode = "wysiwyg";
        setPadding(vditor);
        renderDomByMd(vditor, markdownText, {
            enableAddUndoStack: true,
            enableHint: false,
            enableInput: false,
        });
        vditor.wysiwyg.element.querySelectorAll(".vditor-toc").forEach(function (item) {
            (0,mathRender/* mathRender */.H)(item, {
                cdn: vditor.options.cdn,
                math: vditor.options.preview.math,
            });
        });
        vditor.wysiwyg.popover.style.display = "none";
    }
    else if (type === "sv") {
        showToolbar(vditor.toolbar.elements, ["both"]);
        hideToolbar(vditor.toolbar.elements, ["outdent", "indent", "outline", "insert-before", "insert-after"]);
        vditor.wysiwyg.element.parentElement.style.display = "none";
        vditor.ir.element.parentElement.style.display = "none";
        if (vditor.options.preview.mode === "both") {
            vditor.sv.element.style.display = "block";
        }
        else if (vditor.options.preview.mode === "editor") {
            vditor.sv.element.style.display = "block";
        }
        vditor.lute.SetVditorIR(false);
        vditor.lute.SetVditorWYSIWYG(false);
        vditor.lute.SetVditorSV(true);
        vditor.currentMode = "sv";
        var svHTML = processSpinVditorSVDOM(markdownText, vditor);
        if (svHTML === "<div data-block='0'></div>") {
            // https://github.com/Vanessa219/vditor/issues/654 SV 模式 Placeholder 显示问题
            svHTML = "";
        }
        vditor.sv.element.innerHTML = svHTML;
        combineFootnote(vditor.sv.element);
        processAfterRender(vditor, {
            enableAddUndoStack: true,
            enableHint: false,
            enableInput: false,
        });
        setPadding(vditor);
    }
    vditor.undo.resetIcon(vditor);
    if (typeof event !== "string") {
        // 初始化不 focus
        vditor[vditor.currentMode].element.focus();
        highlightToolbar(vditor);
    }
    renderToc(vditor);
    setTypewriterPosition(vditor);
    if (vditor.toolbar.elements["edit-mode"]) {
        vditor.toolbar.elements["edit-mode"].querySelectorAll("button").forEach(function (item) {
            item.classList.remove("vditor-menu--current");
        });
        vditor.toolbar.elements["edit-mode"].querySelector("button[data-mode=\"".concat(vditor.currentMode, "\"]")).classList.add("vditor-menu--current");
    }
    vditor.outline.toggle(vditor, vditor.currentMode !== "sv" && vditor.options.outline.enable, typeof event !== "string");
};
var EditMode = /** @class */ (function (_super) {
    __extends(EditMode, _super);
    function EditMode(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        var panelElement = document.createElement("div");
        panelElement.className = "vditor-hint".concat(menuItem.level === 2 ? "" : " vditor-panel--arrow");
        panelElement.innerHTML = "<button data-mode=\"wysiwyg\">".concat(window.VditorI18n.wysiwyg, " &lt;").concat((0,compatibility/* updateHotkeyTip */.ns)("⌥⌘7"), "></button>\n<button data-mode=\"ir\">").concat(window.VditorI18n.instantRendering, " &lt;").concat((0,compatibility/* updateHotkeyTip */.ns)("⌥⌘8"), "></button>\n<button data-mode=\"sv\">").concat(window.VditorI18n.splitView, " &lt;").concat((0,compatibility/* updateHotkeyTip */.ns)("⌥⌘9"), "></button>");
        _this.element.appendChild(panelElement);
        _this._bindEvent(vditor, panelElement, menuItem);
        return _this;
    }
    EditMode.prototype._bindEvent = function (vditor, panelElement, menuItem) {
        var actionBtn = this.element.children[0];
        toggleSubMenu(vditor, panelElement, actionBtn, menuItem.level);
        panelElement.children.item(0).addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            // wysiwyg
            setEditMode(vditor, "wysiwyg", event);
            event.preventDefault();
            event.stopPropagation();
        });
        panelElement.children.item(1).addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            // ir
            setEditMode(vditor, "ir", event);
            event.preventDefault();
            event.stopPropagation();
        });
        panelElement.children.item(2).addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            // markdown
            setEditMode(vditor, "sv", event);
            event.preventDefault();
            event.stopPropagation();
        });
    };
    return EditMode;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/util/getSelectText.ts

var getSelectText = function (editor, range) {
    if ((0,selection/* selectIsEditor */.Gb)(editor, range)) {
        return getSelection().toString();
    }
    return "";
};

;// CONCATENATED MODULE: ./src/ts/util/editorCommonEvent.ts


















var focusEvent = function (vditor, editorElement) {
    editorElement.addEventListener("focus", function () {
        if (vditor.options.focus) {
            vditor.options.focus(getMarkdown(vditor));
        }
        hidePanel(vditor, ["subToolbar", "hint"]);
    });
};
var dblclickEvent = function (vditor, editorElement) {
    editorElement.addEventListener("dblclick", function (event) {
        if (event.target.tagName === "IMG") {
            if (vditor.options.image.preview) {
                vditor.options.image.preview(event.target);
            }
            else if (vditor.options.image.isPreview) {
                (0,preview_image/* previewImage */.E)(event.target, vditor.options.lang, vditor.options.theme);
            }
        }
    });
};
var blurEvent = function (vditor, editorElement) {
    editorElement.addEventListener("blur", function (event) {
        if (vditor.currentMode === "ir") {
            var expandElement = vditor.ir.element.querySelector(".vditor-ir__node--expand");
            if (expandElement) {
                expandElement.classList.remove("vditor-ir__node--expand");
            }
        }
        else if (vditor.currentMode === "wysiwyg" &&
            !vditor.wysiwyg.selectPopover.contains(event.relatedTarget)) {
            vditor.wysiwyg.hideComment();
        }
        vditor[vditor.currentMode].range = (0,selection/* getEditorRange */.zh)(vditor);
        if (vditor.options.blur) {
            vditor.options.blur(getMarkdown(vditor));
        }
    });
};
var dropEvent = function (vditor, editorElement) {
    editorElement.addEventListener("dragstart", function (event) {
        // 选中编辑器中的文字进行拖拽
        event.dataTransfer.setData(constants/* Constants.DROP_EDITOR */.g.DROP_EDITOR, constants/* Constants.DROP_EDITOR */.g.DROP_EDITOR);
    });
    editorElement.addEventListener("drop", function (event) {
        if (event.dataTransfer.getData(constants/* Constants.DROP_EDITOR */.g.DROP_EDITOR)) {
            // 编辑器内选中文字拖拽
            execAfterRender(vditor);
        }
        else if (event.dataTransfer.types.includes("Files") || event.dataTransfer.types.includes("text/html")) {
            // 外部文件拖入编辑器中或者编辑器内选中文字拖拽
            paste(vditor, event, {
                pasteCode: function (code) {
                    document.execCommand("insertHTML", false, code);
                },
            });
        }
    });
};
var copyEvent = function (vditor, editorElement, copy) {
    editorElement.addEventListener("copy", function (event) { return copy(event, vditor); });
};
var cutEvent = function (vditor, editorElement, copy) {
    editorElement.addEventListener("cut", function (event) {
        copy(event, vditor);
        // 获取 comment
        if (vditor.options.comment.enable && vditor.currentMode === "wysiwyg") {
            vditor.wysiwyg.getComments(vditor);
        }
        document.execCommand("delete");
    });
};
var scrollCenter = function (vditor) {
    if (vditor.currentMode === "wysiwyg" && vditor.options.comment.enable) {
        vditor.options.comment.adjustTop(vditor.wysiwyg.getComments(vditor, true));
    }
    if (!vditor.options.typewriterMode) {
        return;
    }
    var editorElement = vditor[vditor.currentMode].element;
    var cursorTop = (0,selection/* getCursorPosition */.Ny)(editorElement).top;
    if (vditor.options.height === "auto" && !vditor.element.classList.contains("vditor--fullscreen")) {
        window.scrollTo(window.scrollX, cursorTop + vditor.element.offsetTop + vditor.toolbar.element.offsetHeight - window.innerHeight / 2 + 10);
    }
    if (vditor.options.height !== "auto" || vditor.element.classList.contains("vditor--fullscreen")) {
        editorElement.scrollTop = cursorTop + editorElement.scrollTop - editorElement.clientHeight / 2 + 10;
    }
};
var hotkeyEvent = function (vditor, editorElement) {
    editorElement.addEventListener("keydown", function (event) {
        if (!event.isComposing && vditor.options.keydown) {
            vditor.options.keydown(event);
        }
        // hint: 上下选择
        if ((vditor.options.hint.extend.length > 1 || vditor.toolbar.elements.emoji) &&
            vditor.hint.select(event, vditor)) {
            return;
        }
        // 重置 comment
        if (vditor.options.comment.enable && vditor.currentMode === "wysiwyg" &&
            (event.key === "Backspace" || matchHotKey("⌘X", event))) {
            vditor.wysiwyg.getComments(vditor);
        }
        if (vditor.currentMode === "sv") {
            if (processKeydown_processKeydown(vditor, event)) {
                return;
            }
        }
        else if (vditor.currentMode === "wysiwyg") {
            if (wysiwyg_processKeydown_processKeydown(vditor, event)) {
                return;
            }
        }
        else if (vditor.currentMode === "ir") {
            if (processKeydown(vditor, event)) {
                return;
            }
        }
        if (vditor.options.ctrlEnter && matchHotKey("⌘Enter", event)) {
            vditor.options.ctrlEnter(getMarkdown(vditor));
            event.preventDefault();
            return;
        }
        // undo
        if (matchHotKey("⌘Z", event) && !vditor.toolbar.elements.undo) {
            vditor.undo.undo(vditor);
            event.preventDefault();
            return;
        }
        // redo
        if (matchHotKey("⌘Y", event) && !vditor.toolbar.elements.redo) {
            vditor.undo.redo(vditor);
            event.preventDefault();
            return;
        }
        // esc
        if (event.key === "Escape") {
            if (vditor.hint.element.style.display === "block") {
                vditor.hint.element.style.display = "none";
            }
            else if (vditor.options.esc && !event.isComposing) {
                vditor.options.esc(getMarkdown(vditor));
            }
            event.preventDefault();
            return;
        }
        // h1 - h6 hotkey
        if ((0,compatibility/* isCtrl */.yl)(event) && event.altKey && !event.shiftKey && /^Digit[1-6]$/.test(event.code)) {
            if (vditor.currentMode === "wysiwyg") {
                var tagName = event.code.replace("Digit", "H");
                if ((0,hasClosest/* hasClosestByMatchTag */.lG)(getSelection().getRangeAt(0).startContainer, tagName)) {
                    removeHeading(vditor);
                }
                else {
                    setHeading(vditor, tagName);
                }
                afterRenderEvent(vditor);
            }
            else if (vditor.currentMode === "sv") {
                processHeading(vditor, "#".repeat(parseInt(event.code.replace("Digit", ""), 10)) + " ");
            }
            else if (vditor.currentMode === "ir") {
                process_processHeading(vditor, "#".repeat(parseInt(event.code.replace("Digit", ""), 10)) + " ");
            }
            event.preventDefault();
            return true;
        }
        // toggle edit mode
        if ((0,compatibility/* isCtrl */.yl)(event) && event.altKey && !event.shiftKey && /^Digit[7-9]$/.test(event.code)) {
            if (event.code === "Digit7") {
                setEditMode(vditor, "wysiwyg", event);
            }
            else if (event.code === "Digit8") {
                setEditMode(vditor, "ir", event);
            }
            else if (event.code === "Digit9") {
                setEditMode(vditor, "sv", event);
            }
            return true;
        }
        // toolbar action
        vditor.options.toolbar.find(function (menuItem) {
            if (!menuItem.hotkey || menuItem.toolbar) {
                if (menuItem.toolbar) {
                    var sub = menuItem.toolbar.find(function (subMenuItem) {
                        if (!subMenuItem.hotkey) {
                            return false;
                        }
                        if (matchHotKey(subMenuItem.hotkey, event)) {
                            vditor.toolbar.elements[subMenuItem.name].children[0]
                                .dispatchEvent(new CustomEvent((0,compatibility/* getEventName */.Le)()));
                            event.preventDefault();
                            return true;
                        }
                    });
                    return sub ? true : false;
                }
                return false;
            }
            if (matchHotKey(menuItem.hotkey, event)) {
                vditor.toolbar.elements[menuItem.name].children[0].dispatchEvent(new CustomEvent((0,compatibility/* getEventName */.Le)()));
                event.preventDefault();
                return true;
            }
        });
    });
};
var selectEvent = function (vditor, editorElement) {
    editorElement.addEventListener("selectstart", function (event) {
        editorElement.onmouseup = function () {
            setTimeout(function () {
                var selectText = getSelectText(vditor[vditor.currentMode].element);
                if (selectText.trim()) {
                    if (vditor.currentMode === "wysiwyg" && vditor.options.comment.enable) {
                        if (!(0,hasClosest/* hasClosestByAttribute */.a1)(event.target, "data-type", "footnotes-block") &&
                            !(0,hasClosest/* hasClosestByAttribute */.a1)(event.target, "data-type", "link-ref-defs-block")) {
                            vditor.wysiwyg.showComment();
                        }
                        else {
                            vditor.wysiwyg.hideComment();
                        }
                    }
                    if (vditor.options.select) {
                        vditor.options.select(selectText);
                    }
                }
                else {
                    if (vditor.currentMode === "wysiwyg" && vditor.options.comment.enable) {
                        vditor.wysiwyg.hideComment();
                    }
                }
            });
        };
    });
};

;// CONCATENATED MODULE: ./src/ts/sv/process.ts









var processPaste = function (vditor, text) {
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    range.extractContents();
    range.insertNode(document.createTextNode(Lute.Caret));
    range.insertNode(document.createTextNode(text));
    var blockElement = (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-block", "0");
    if (!blockElement) {
        blockElement = vditor.sv.element;
    }
    var spinHTML = vditor.lute.SpinVditorSVDOM(blockElement.textContent);
    spinHTML = "<div data-block='0'>" +
        spinHTML.replace(/<span data-type="newline"><br \/><span style="display: none">\n<\/span><\/span><span data-type="newline"><br \/><span style="display: none">\n<\/span><\/span></g, '<span data-type="newline"><br /><span style="display: none">\n</span></span><span data-type="newline"><br /><span style="display: none">\n</span></span></div><div data-block="0"><') +
        "</div>";
    if (blockElement.isEqualNode(vditor.sv.element)) {
        blockElement.innerHTML = spinHTML;
    }
    else {
        blockElement.outerHTML = spinHTML;
    }
    combineFootnote(vditor.sv.element);
    (0,selection/* setRangeByWbr */.ib)(vditor.sv.element, range);
    scrollCenter(vditor);
};
var getSideByType = function (spanNode, type, isPrevious) {
    if (isPrevious === void 0) { isPrevious = true; }
    var sideElement = spanNode;
    if (sideElement.nodeType === 3) {
        sideElement = sideElement.parentElement;
    }
    while (sideElement) {
        if (sideElement.getAttribute("data-type") === type) {
            return sideElement;
        }
        if (isPrevious) {
            sideElement = sideElement.previousElementSibling;
        }
        else {
            sideElement = sideElement.nextElementSibling;
        }
    }
    return false;
};
var processSpinVditorSVDOM = function (html, vditor) {
    log("SpinVditorSVDOM", html, "argument", vditor.options.debugger);
    var spinHTML = vditor.lute.SpinVditorSVDOM(html);
    html = "<div data-block='0'>" +
        spinHTML.replace(/<span data-type="newline"><br \/><span style="display: none">\n<\/span><\/span><span data-type="newline"><br \/><span style="display: none">\n<\/span><\/span></g, '<span data-type="newline"><br /><span style="display: none">\n</span></span><span data-type="newline"><br /><span style="display: none">\n</span></span></div><div data-block="0"><') +
        "</div>";
    log("SpinVditorSVDOM", html, "result", vditor.options.debugger);
    return html;
};
var processPreviousMarkers = function (spanElement) {
    var spanType = spanElement.getAttribute("data-type");
    var previousElement = spanElement.previousElementSibling;
    // 有内容的子列表/标题，在其 marker 后换行
    var markerText = (spanType && spanType !== "text" && spanType !== "table" && spanType !== "heading-marker" &&
        spanType !== "newline" && spanType !== "yaml-front-matter-open-marker" && spanType !== "yaml-front-matter-close-marker"
        && spanType !== "code-block-info" && spanType !== "code-block-close-marker" && spanType !== "code-block-open-marker") ?
        spanElement.textContent : "";
    var hasNL = false;
    if (spanType === "newline") {
        hasNL = true;
    }
    while (previousElement && !hasNL) {
        var previousType = previousElement.getAttribute("data-type");
        if (previousType === "li-marker" || previousType === "blockquote-marker" || previousType === "task-marker" ||
            previousType === "padding") {
            var previousText = previousElement.textContent;
            if (previousType === "li-marker" &&
                (spanType === "code-block-open-marker" || spanType === "code-block-info")) {
                // https://github.com/Vanessa219/vditor/issues/586
                markerText = previousText.replace(/\S/g, " ") + markerText;
            }
            else if (spanType === "code-block-close-marker" &&
                previousElement.nextElementSibling.isSameNode(spanElement)) {
                // https://github.com/Vanessa219/vditor/issues/594
                var openMarker = getSideByType(spanElement, "code-block-open-marker");
                if (openMarker && openMarker.previousElementSibling) {
                    previousElement = openMarker.previousElementSibling;
                    markerText = previousText + markerText;
                }
            }
            else {
                markerText = previousText + markerText;
            }
        }
        else if (previousType === "newline") {
            hasNL = true;
        }
        previousElement = previousElement.previousElementSibling;
    }
    return markerText;
};
var processAfterRender = function (vditor, options) {
    if (options === void 0) { options = {
        enableAddUndoStack: true,
        enableHint: false,
        enableInput: true,
    }; }
    if (options.enableHint) {
        vditor.hint.render(vditor);
    }
    vditor.preview.render(vditor);
    var text = getMarkdown(vditor);
    if (typeof vditor.options.input === "function" && options.enableInput) {
        vditor.options.input(text);
    }
    if (vditor.options.counter.enable) {
        vditor.counter.render(vditor, text);
    }
    if (vditor.options.cache.enable && (0,compatibility/* accessLocalStorage */.pK)()) {
        localStorage.setItem(vditor.options.cache.id, text);
        if (vditor.options.cache.after) {
            vditor.options.cache.after(text);
        }
    }
    if (vditor.devtools) {
        vditor.devtools.renderEchart(vditor);
    }
    clearTimeout(vditor.sv.processTimeoutId);
    vditor.sv.processTimeoutId = window.setTimeout(function () {
        if (options.enableAddUndoStack && !vditor.sv.composingLock) {
            vditor.undo.addToUndoStack(vditor);
        }
    }, vditor.options.undoDelay);
};
var processHeading = function (vditor, value) {
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var headingElement = (0,hasClosestByHeadings/* hasClosestByTag */.S)(range.startContainer, "SPAN");
    if (headingElement && headingElement.textContent.trim() !== "") {
        value = "\n" + value;
    }
    range.collapse(true);
    document.execCommand("insertHTML", false, value);
};
var processToolbar = function (vditor, actionBtn, prefix, suffix) {
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var commandName = actionBtn.getAttribute("data-type");
    // 添加
    if (vditor.sv.element.childNodes.length === 0) {
        vditor.sv.element.innerHTML = "<span data-type=\"p\" data-block=\"0\"><span data-type=\"text\"><wbr></span></span><span data-type=\"newline\"><br><span style=\"display: none\">\n</span></span>";
        (0,selection/* setRangeByWbr */.ib)(vditor.sv.element, range);
    }
    var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
    var spanElement = (0,hasClosestByHeadings/* hasClosestByTag */.S)(range.startContainer, "SPAN");
    if (!blockElement) {
        return;
    }
    if (commandName === "link") {
        var html = void 0;
        if (range.toString() === "") {
            html = "".concat(prefix).concat(Lute.Caret).concat(suffix);
        }
        else {
            html = "".concat(prefix).concat(range.toString()).concat(suffix.replace(")", Lute.Caret + ")"));
        }
        document.execCommand("insertHTML", false, html);
        return;
    }
    else if (commandName === "italic" || commandName === "bold" || commandName === "strike" ||
        commandName === "inline-code" || commandName === "code" || commandName === "table" || commandName === "line") {
        var html = void 0;
        // https://github.com/Vanessa219/vditor/issues/563 代码块不需要后面的 ```
        if (range.toString() === "") {
            html = "".concat(prefix).concat(Lute.Caret).concat(commandName === "code" ? "" : suffix);
        }
        else {
            html = "".concat(prefix).concat(range.toString()).concat(Lute.Caret).concat(commandName === "code" ? "" : suffix);
        }
        if (commandName === "table" || (commandName === "code" && spanElement && spanElement.textContent !== "")) {
            html = "\n\n" + html;
        }
        else if (commandName === "line") {
            html = "\n\n".concat(prefix, "\n").concat(Lute.Caret);
        }
        document.execCommand("insertHTML", false, html);
        return;
    }
    else if (commandName === "check" || commandName === "list" || commandName === "ordered-list" ||
        commandName === "quote") {
        if (spanElement) {
            var marker = "* ";
            if (commandName === "check") {
                marker = "* [ ] ";
            }
            else if (commandName === "ordered-list") {
                marker = "1. ";
            }
            else if (commandName === "quote") {
                marker = "> ";
            }
            var newLine = getSideByType(spanElement, "newline");
            if (newLine) {
                newLine.insertAdjacentText("afterend", marker);
            }
            else {
                blockElement.insertAdjacentText("afterbegin", marker);
            }
            inputEvent(vditor);
            return;
        }
    }
    (0,selection/* setRangeByWbr */.ib)(vditor.sv.element, range);
    processAfterRender(vditor);
};

;// CONCATENATED MODULE: ./src/ts/upload/getElement.ts
var getElement = function (vditor) {
    switch (vditor.currentMode) {
        case "ir":
            return vditor.ir.element;
        case "wysiwyg":
            return vditor.wysiwyg.element;
        case "sv":
            return vditor.sv.element;
    }
};

;// CONCATENATED MODULE: ./src/ts/upload/setHeaders.ts
var setHeaders = function (vditor, xhr) {
    if (vditor.options.upload.setHeaders) {
        vditor.options.upload.headers = vditor.options.upload.setHeaders();
    }
    if (vditor.options.upload.headers) {
        Object.keys(vditor.options.upload.headers).forEach(function (key) {
            xhr.setRequestHeader(key, vditor.options.upload.headers[key]);
        });
    }
};

;// CONCATENATED MODULE: ./src/ts/upload/index.ts
var __awaiter = (undefined && undefined.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (undefined && undefined.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g;
    return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};



var Upload = /** @class */ (function () {
    function Upload() {
        this.isUploading = false;
        this.element = document.createElement("div");
        this.element.className = "vditor-upload";
    }
    return Upload;
}());
var validateFile = function (vditor, files) {
    vditor.tip.hide();
    var uploadFileList = [];
    var errorTip = "";
    var uploadingStr = "";
    var lang = vditor.options.lang;
    var options = vditor.options;
    var _loop_1 = function (iMax, i) {
        var file = files[i];
        var validate = true;
        if (!file.name) {
            errorTip += "<li>".concat(window.VditorI18n.nameEmpty, "</li>");
            validate = false;
        }
        if (file.size > vditor.options.upload.max) {
            errorTip += "<li>".concat(file.name, " ").concat(window.VditorI18n.over, " ").concat(vditor.options.upload.max / 1024 / 1024, "M</li>");
            validate = false;
        }
        var lastIndex = file.name.lastIndexOf(".");
        var fileExt = file.name.substr(lastIndex);
        var filename = vditor.options.upload.filename(file.name.substr(0, lastIndex)) + fileExt;
        if (vditor.options.upload.accept) {
            var isAccept = vditor.options.upload.accept.split(",").some(function (item) {
                var type = item.trim();
                if (type.indexOf(".") === 0) {
                    if (fileExt.toLowerCase() === type.toLowerCase()) {
                        return true;
                    }
                }
                else {
                    if (file.type.split("/")[0] === type.split("/")[0]) {
                        return true;
                    }
                }
                return false;
            });
            if (!isAccept) {
                errorTip += "<li>".concat(file.name, " ").concat(window.VditorI18n.fileTypeError, "</li>");
                validate = false;
            }
        }
        if (validate) {
            uploadFileList.push(file);
            uploadingStr += "<li>".concat(filename, " ").concat(window.VditorI18n.uploading, "</li>");
        }
    };
    for (var iMax = files.length, i = 0; i < iMax; i++) {
        _loop_1(iMax, i);
    }
    vditor.tip.show("<ul>".concat(errorTip).concat(uploadingStr, "</ul>"));
    return uploadFileList;
};
var genUploadedLabel = function (responseText, vditor) {
    var editorElement = getElement(vditor);
    editorElement.focus();
    var response = JSON.parse(responseText);
    var errorTip = "";
    if (response.code === 1) {
        errorTip = "".concat(response.msg);
    }
    if (response.data.errFiles && response.data.errFiles.length > 0) {
        errorTip = "<ul><li>".concat(errorTip, "</li>");
        response.data.errFiles.forEach(function (data) {
            var lastIndex = data.lastIndexOf(".");
            var filename = vditor.options.upload.filename(data.substr(0, lastIndex)) + data.substr(lastIndex);
            errorTip += "<li>".concat(filename, " ").concat(window.VditorI18n.uploadError, "</li>");
        });
        errorTip += "</ul>";
    }
    if (errorTip) {
        vditor.tip.show(errorTip);
    }
    else {
        vditor.tip.hide();
    }
    var succFileText = "";
    Object.keys(response.data.succMap).forEach(function (key) {
        var path = response.data.succMap[key];
        var lastIndex = key.lastIndexOf(".");
        var type = key.substr(lastIndex);
        var filename = vditor.options.upload.filename(key.substr(0, lastIndex)) + type;
        type = type.toLowerCase();
        if (type.indexOf(".wav") === 0 || type.indexOf(".mp3") === 0 || type.indexOf(".ogg") === 0) {
            if (vditor.currentMode === "wysiwyg") {
                succFileText += "<div class=\"vditor-wysiwyg__block\" data-type=\"html-block\"\n data-block=\"0\"><pre><code>&lt;audio controls=\"controls\" src=\"".concat(path, "\"&gt;&lt;/audio&gt;</code></pre><pre class=\"vditor-wysiwyg__preview\" data-render=\"1\"><audio controls=\"controls\" src=\"").concat(path, "\"></audio></pre></div>\n");
            }
            else if (vditor.currentMode === "ir") {
                succFileText += "<audio controls=\"controls\" src=\"".concat(path, "\"></audio>\n");
            }
            else {
                succFileText += "[".concat(filename, "](").concat(path, ")\n");
            }
        }
        else if (type.indexOf(".apng") === 0
            || type.indexOf(".bmp") === 0
            || type.indexOf(".gif") === 0
            || type.indexOf(".ico") === 0 || type.indexOf(".cur") === 0
            || type.indexOf(".jpg") === 0 || type.indexOf(".jpeg") === 0 || type.indexOf(".jfif") === 0 || type.indexOf(".pjp") === 0 || type.indexOf(".pjpeg") === 0
            || type.indexOf(".png") === 0
            || type.indexOf(".svg") === 0
            || type.indexOf(".webp") === 0) {
            if (vditor.currentMode === "wysiwyg") {
                succFileText += "<img alt=\"".concat(filename, "\" src=\"").concat(path, "\">\n");
            }
            else {
                succFileText += "![".concat(filename, "](").concat(path, ")\n");
            }
        }
        else {
            if (vditor.currentMode === "wysiwyg") {
                succFileText += "<a href=\"".concat(path, "\">").concat(filename, "</a>\n");
            }
            else {
                succFileText += "[".concat(filename, "](").concat(path, ")\n");
            }
        }
    });
    (0,selection/* setSelectionFocus */.Hc)(vditor.upload.range);
    document.execCommand("insertHTML", false, succFileText);
    vditor.upload.range = getSelection().getRangeAt(0).cloneRange();
};
var uploadFiles = function (vditor, files, element) { return __awaiter(void 0, void 0, void 0, function () {
    var fileList, filesMax, i, fileItem, isValidate, isValidate, editorElement, validateResult, formData, extraData, _i, _a, key, i, iMax, xhr;
    return __generator(this, function (_b) {
        switch (_b.label) {
            case 0:
                fileList = [];
                filesMax = vditor.options.upload.multiple === true ? files.length : 1;
                for (i = 0; i < filesMax; i++) {
                    fileItem = files[i];
                    if (fileItem instanceof DataTransferItem) {
                        fileItem = fileItem.getAsFile();
                    }
                    fileList.push(fileItem);
                }
                if (!vditor.options.upload.handler) return [3 /*break*/, 2];
                return [4 /*yield*/, vditor.options.upload.handler(fileList)];
            case 1:
                isValidate = _b.sent();
                if (element) {
                    element.value = "";
                }
                if (typeof isValidate === "string") {
                    vditor.tip.show(isValidate);
                    return [2 /*return*/];
                }
                return [2 /*return*/];
            case 2:
                if (!vditor.options.upload.url || !vditor.upload) {
                    if (element) {
                        element.value = "";
                    }
                    vditor.tip.show("please config: options.upload.url");
                    return [2 /*return*/];
                }
                if (!vditor.options.upload.file) return [3 /*break*/, 4];
                return [4 /*yield*/, vditor.options.upload.file(fileList)];
            case 3:
                fileList = _b.sent();
                _b.label = 4;
            case 4:
                if (vditor.options.upload.validate) {
                    isValidate = vditor.options.upload.validate(fileList);
                    if (typeof isValidate === "string") {
                        vditor.tip.show(isValidate);
                        return [2 /*return*/];
                    }
                }
                editorElement = getElement(vditor);
                vditor.upload.range = (0,selection/* getEditorRange */.zh)(vditor);
                validateResult = validateFile(vditor, fileList);
                if (validateResult.length === 0) {
                    if (element) {
                        element.value = "";
                    }
                    return [2 /*return*/];
                }
                formData = new FormData();
                extraData = vditor.options.upload.extraData;
                for (_i = 0, _a = Object.keys(extraData); _i < _a.length; _i++) {
                    key = _a[_i];
                    formData.append(key, extraData[key]);
                }
                for (i = 0, iMax = validateResult.length; i < iMax; i++) {
                    formData.append(vditor.options.upload.fieldName, validateResult[i]);
                }
                xhr = new XMLHttpRequest();
                xhr.open("POST", vditor.options.upload.url);
                if (vditor.options.upload.token) {
                    xhr.setRequestHeader("X-Upload-Token", vditor.options.upload.token);
                }
                if (vditor.options.upload.withCredentials) {
                    xhr.withCredentials = true;
                }
                setHeaders(vditor, xhr);
                vditor.upload.isUploading = true;
                editorElement.setAttribute("contenteditable", "false");
                xhr.onreadystatechange = function () {
                    if (xhr.readyState === XMLHttpRequest.DONE) {
                        vditor.upload.isUploading = false;
                        editorElement.setAttribute("contenteditable", "true");
                        if (xhr.status >= 200 && xhr.status < 300) {
                            if (vditor.options.upload.success) {
                                vditor.options.upload.success(editorElement, xhr.responseText);
                            }
                            else {
                                var responseText = xhr.responseText;
                                if (vditor.options.upload.format) {
                                    responseText = vditor.options.upload.format(files, xhr.responseText);
                                }
                                genUploadedLabel(responseText, vditor);
                            }
                        }
                        else {
                            if (vditor.options.upload.error) {
                                vditor.options.upload.error(xhr.responseText);
                            }
                            else {
                                vditor.tip.show(xhr.responseText);
                            }
                        }
                        if (element) {
                            element.value = "";
                        }
                        vditor.upload.element.style.display = "none";
                    }
                };
                xhr.upload.onprogress = function (event) {
                    if (!event.lengthComputable) {
                        return;
                    }
                    var progress = event.loaded / event.total * 100;
                    vditor.upload.element.style.display = "block";
                    var progressBar = vditor.upload.element;
                    progressBar.style.width = progress + "%";
                };
                xhr.send(formData);
                return [2 /*return*/];
        }
    });
}); };


;// CONCATENATED MODULE: ./src/ts/wysiwyg/input.ts








var input_input = function (vditor, range, event) {
    var _a;
    var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
    if (!blockElement) {
        // 使用顶级块元素，应使用 innerHTML
        blockElement = vditor.wysiwyg.element;
    }
    if (event && event.inputType !== "formatItalic"
        && event.inputType !== "deleteByDrag"
        && event.inputType !== "insertFromDrop"
        && event.inputType !== "formatBold"
        && event.inputType !== "formatRemove"
        && event.inputType !== "formatStrikeThrough"
        && event.inputType !== "insertUnorderedList"
        && event.inputType !== "insertOrderedList"
        && event.inputType !== "formatOutdent"
        && event.inputType !== "formatIndent"
        && event.inputType !== "" // document.execCommand('unlink', false)
        || !event) {
        var previousAEmptyElement = previoueIsEmptyA(range.startContainer);
        if (previousAEmptyElement) {
            // 链接结尾回车不应该复制到下一行 https://github.com/Vanessa219/vditor/issues/163
            previousAEmptyElement.remove();
        }
        // 保存光标
        vditor.wysiwyg.element.querySelectorAll("wbr").forEach(function (wbr) {
            wbr.remove();
        });
        range.insertNode(document.createElement("wbr"));
        // 在行首进行删除，后面的元素会带有样式，需清除
        blockElement.querySelectorAll("[style]").forEach(function (item) {
            item.removeAttribute("style");
        });
        // 移除空评论
        blockElement.querySelectorAll(".vditor-comment").forEach(function (item) {
            if (item.textContent.trim() === "") {
                item.classList.remove("vditor-comment", "vditor-comment--focus");
                item.removeAttribute("data-cmtids");
            }
        });
        //  在有评论的行首换行后，该行的前一段会带有评论标识
        (_a = blockElement.previousElementSibling) === null || _a === void 0 ? void 0 : _a.querySelectorAll(".vditor-comment").forEach(function (item) {
            if (item.textContent.trim() === "") {
                item.classList.remove("vditor-comment", "vditor-comment--focus");
                item.removeAttribute("data-cmtids");
            }
        });
        var html_1 = "";
        if (blockElement.getAttribute("data-type") === "link-ref-defs-block") {
            // 修改链接引用
            blockElement = vditor.wysiwyg.element;
        }
        var isWYSIWYGElement = blockElement.isEqualNode(vditor.wysiwyg.element);
        var footnoteElement = (0,hasClosest/* hasClosestByAttribute */.a1)(blockElement, "data-type", "footnotes-block");
        if (!isWYSIWYGElement) {
            // 列表需要到最顶层
            var topListElement = (0,hasClosest/* getTopList */.O9)(range.startContainer);
            if (topListElement && !footnoteElement) {
                var blockquoteElement = (0,hasClosestByHeadings/* hasClosestByTag */.S)(range.startContainer, "BLOCKQUOTE");
                if (blockquoteElement) {
                    // li 中有 blockquote 就只渲染 blockquote
                    blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer) || blockElement;
                }
                else {
                    blockElement = topListElement;
                }
            }
            // 修改脚注
            if (footnoteElement) {
                blockElement = footnoteElement;
            }
            html_1 = blockElement.outerHTML;
            if (blockElement.tagName === "UL" || blockElement.tagName === "OL") {
                // 如果为列表的话，需要把上下的列表都重绘
                var listPrevElement = blockElement.previousElementSibling;
                var listNextElement = blockElement.nextElementSibling;
                if (listPrevElement && (listPrevElement.tagName === "UL" || listPrevElement.tagName === "OL")) {
                    html_1 = listPrevElement.outerHTML + html_1;
                    listPrevElement.remove();
                }
                if (listNextElement && (listNextElement.tagName === "UL" || listNextElement.tagName === "OL")) {
                    html_1 = html_1 + listNextElement.outerHTML;
                    listNextElement.remove();
                }
                // firefox 列表回车不会产生新的 list item https://github.com/Vanessa219/vditor/issues/194
                html_1 = html_1.replace("<div><wbr><br></div>", "<li><p><wbr><br></p></li>");
            }
            if (!blockElement.innerText.startsWith("```")) {
                // 添加链接引用
                vditor.wysiwyg.element.querySelectorAll("[data-type='link-ref-defs-block']").forEach(function (item) {
                    if (item && !blockElement.isEqualNode(item)) {
                        html_1 += item.outerHTML;
                        item.remove();
                    }
                });
                // 添加脚注
                vditor.wysiwyg.element.querySelectorAll("[data-type='footnotes-block']").forEach(function (item) {
                    if (item && !blockElement.isEqualNode(item)) {
                        html_1 += item.outerHTML;
                        item.remove();
                    }
                });
            }
        }
        else {
            html_1 = blockElement.innerHTML;
        }
        // 合并多个 em， strong，s。以防止多个相同元素在一起时不满足 commonmark 规范，出现标记符
        html_1 = html_1.replace(/<\/(strong|b)><strong data-marker="\W{2}">/g, "")
            .replace(/<\/(em|i)><em data-marker="\W{1}">/g, "")
            .replace(/<\/(s|strike)><s data-marker="~{1,2}">/g, "");
        if (html_1 === '<p data-block="0">```<wbr></p>' && vditor.hint.recentLanguage) {
            html_1 = '<p data-block="0">```<wbr></p>'.replace("```", "```" + vditor.hint.recentLanguage);
        }
        log("SpinVditorDOM", html_1, "argument", vditor.options.debugger);
        html_1 = vditor.lute.SpinVditorDOM(html_1);
        log("SpinVditorDOM", html_1, "result", vditor.options.debugger);
        if (isWYSIWYGElement) {
            blockElement.innerHTML = html_1;
        }
        else {
            blockElement.outerHTML = html_1;
            if (footnoteElement) {
                // 更新正文中的 tip
                var footnoteItemElement = (0,hasClosest/* hasTopClosestByTag */.E2)(vditor.wysiwyg.element.querySelector("wbr"), "LI");
                if (footnoteItemElement) {
                    var footnoteRefElement = vditor.wysiwyg.element.querySelector("sup[data-type=\"footnotes-ref\"][data-footnotes-label=\"".concat(footnoteItemElement.getAttribute("data-marker"), "\"]"));
                    if (footnoteRefElement) {
                        footnoteRefElement.setAttribute("aria-label", footnoteItemElement.textContent.trim().substr(0, 24));
                    }
                }
            }
        }
        var firstLinkRefDefElement_1;
        var allLinkRefDefsElement = vditor.wysiwyg.element.querySelectorAll("[data-type='link-ref-defs-block']");
        allLinkRefDefsElement.forEach(function (item, index) {
            if (index === 0) {
                firstLinkRefDefElement_1 = item;
            }
            else {
                firstLinkRefDefElement_1.insertAdjacentHTML("beforeend", item.innerHTML);
                item.remove();
            }
        });
        if (allLinkRefDefsElement.length > 0) {
            vditor.wysiwyg.element.insertAdjacentElement("beforeend", allLinkRefDefsElement[0]);
        }
        // 脚注合并后添加的末尾
        var firstFootnoteElement_1;
        var allFootnoteElement = vditor.wysiwyg.element.querySelectorAll("[data-type='footnotes-block']");
        allFootnoteElement.forEach(function (item, index) {
            if (index === 0) {
                firstFootnoteElement_1 = item;
            }
            else {
                firstFootnoteElement_1.insertAdjacentHTML("beforeend", item.innerHTML);
                item.remove();
            }
        });
        if (allFootnoteElement.length > 0) {
            vditor.wysiwyg.element.insertAdjacentElement("beforeend", allFootnoteElement[0]);
        }
        // 设置光标
        (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
        vditor.wysiwyg.element.querySelectorAll(".vditor-wysiwyg__preview[data-render='2']")
            .forEach(function (item) {
            processCodeRender(item, vditor);
        });
        if (event && (event.inputType === "deleteContentBackward" || event.inputType === "deleteContentForward") &&
            vditor.options.comment.enable) {
            vditor.wysiwyg.triggerRemoveComment(vditor);
            vditor.options.comment.adjustTop(vditor.wysiwyg.getComments(vditor, true));
        }
    }
    renderToc(vditor);
    afterRenderEvent(vditor, {
        enableAddUndoStack: true,
        enableHint: true,
        enableInput: true,
    });
};

;// CONCATENATED MODULE: ./src/ts/util/fixBrowserBehavior.ts
var __makeTemplateObject = (undefined && undefined.__makeTemplateObject) || function (cooked, raw) {
    if (Object.defineProperty) { Object.defineProperty(cooked, "raw", { value: raw }); } else { cooked.raw = raw; }
    return cooked;
};
var fixBrowserBehavior_awaiter = (undefined && undefined.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var fixBrowserBehavior_generator = (undefined && undefined.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g;
    return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
















// https://github.com/Vanessa219/vditor/issues/508 软键盘无法删除空块
var fixGSKeyBackspace = function (event, vditor, startContainer) {
    if (event.keyCode === 229 && event.code === "" && event.key === "Unidentified" && vditor.currentMode !== "sv") {
        var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(startContainer);
        // 移动端的标点符号都显示为 299，因此需限定为空删除的条件
        if (blockElement && blockElement.textContent.trim() === "") {
            vditor[vditor.currentMode].composingLock = true;
            return false;
        }
    }
    return true;
};
// https://github.com/Vanessa219/vditor/issues/361 代码块后输入中文
var fixCJKPosition = function (range, vditor, event) {
    if (event.key === "Enter" || event.key === "Tab" || event.key === "Backspace" || event.key.indexOf("Arrow") > -1
        || (0,compatibility/* isCtrl */.yl)(event) || event.key === "Escape" || event.shiftKey || event.altKey) {
        return;
    }
    var pLiElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "P") ||
        (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "LI");
    if (pLiElement && (0,selection/* getSelectPosition */.im)(pLiElement, vditor[vditor.currentMode].element, range).start === 0) {
        // https://github.com/Vanessa219/vditor/issues/1289 WKWebView切换输入法产生六分之一空格，造成光标错位
        if (pLiElement.nodeValue) {
            pLiElement.nodeValue = pLiElement.nodeValue.replace(/\u2006/g, '');
        }
        var zwspNode = document.createTextNode(constants/* Constants.ZWSP */.g.ZWSP);
        range.insertNode(zwspNode);
        range.setStartAfter(zwspNode);
    }
};
// https://github.com/Vanessa219/vditor/issues/381 光标在内联数学公式中无法向下移动
var fixCursorDownInlineMath = function (range, key) {
    if (key === "ArrowDown" || key === "ArrowUp") {
        var inlineElement = (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-type", "math-inline") ||
            (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-type", "html-entity") ||
            (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-type", "html-inline");
        if (inlineElement) {
            if (key === "ArrowDown") {
                range.setStartAfter(inlineElement.parentElement);
            }
            if (key === "ArrowUp") {
                range.setStartBefore(inlineElement.parentElement);
            }
        }
    }
};
var insertEmptyBlock = function (vditor, position) {
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
    if (blockElement) {
        blockElement.insertAdjacentHTML(position, "<p data-block=\"0\">".concat(constants/* Constants.ZWSP */.g.ZWSP, "<wbr>\n</p>"));
        (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
        highlightToolbar(vditor);
        execAfterRender(vditor);
    }
};
var isFirstCell = function (cellElement) {
    var tableElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(cellElement, "TABLE");
    if (tableElement && tableElement.rows[0].cells[0].isSameNode(cellElement)) {
        return tableElement;
    }
    return false;
};
var isLastCell = function (cellElement) {
    var tableElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(cellElement, "TABLE");
    if (tableElement && tableElement.lastElementChild.lastElementChild.lastElementChild.isSameNode(cellElement)) {
        return tableElement;
    }
    return false;
};
// 光标设置到前一个表格中
var goPreviousCell = function (cellElement, range, isSelected) {
    if (isSelected === void 0) { isSelected = true; }
    var previousElement = cellElement.previousElementSibling;
    if (!previousElement) {
        if (cellElement.parentElement.previousElementSibling) {
            previousElement = cellElement.parentElement.previousElementSibling.lastElementChild;
        }
        else if (cellElement.parentElement.parentElement.tagName === "TBODY" &&
            cellElement.parentElement.parentElement.previousElementSibling) {
            previousElement = cellElement.parentElement
                .parentElement.previousElementSibling.lastElementChild.lastElementChild;
        }
        else {
            previousElement = null;
        }
    }
    if (previousElement) {
        range.selectNodeContents(previousElement);
        if (!isSelected) {
            range.collapse(false);
        }
        (0,selection/* setSelectionFocus */.Hc)(range);
    }
    return previousElement;
};
var insertAfterBlock = function (vditor, event, range, element, blockElement) {
    var position = (0,selection/* getSelectPosition */.im)(element, vditor[vditor.currentMode].element, range);
    if ((event.key === "ArrowDown" && element.textContent.trimRight().substr(position.start).indexOf("\n") === -1) ||
        (event.key === "ArrowRight" && position.start >= element.textContent.trimRight().length)) {
        var nextElement = blockElement.nextElementSibling;
        if (!nextElement ||
            (nextElement && (nextElement.tagName === "TABLE" || nextElement.getAttribute("data-type")))) {
            blockElement.insertAdjacentHTML("afterend", "<p data-block=\"0\">".concat(constants/* Constants.ZWSP */.g.ZWSP, "<wbr></p>"));
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
        }
        else {
            range.selectNodeContents(nextElement);
            range.collapse(true);
            (0,selection/* setSelectionFocus */.Hc)(range);
        }
        event.preventDefault();
        return true;
    }
    return false;
};
var insertBeforeBlock = function (vditor, event, range, element, blockElement) {
    var position = (0,selection/* getSelectPosition */.im)(element, vditor[vditor.currentMode].element, range);
    if ((event.key === "ArrowUp" && element.textContent.substr(0, position.start).indexOf("\n") === -1) ||
        ((event.key === "ArrowLeft" || (event.key === "Backspace" && range.toString() === "")) &&
            position.start === 0)) {
        var previousElement = blockElement.previousElementSibling;
        // table || code
        if (!previousElement ||
            (previousElement && (previousElement.tagName === "TABLE" || previousElement.getAttribute("data-type")))) {
            blockElement.insertAdjacentHTML("beforebegin", "<p data-block=\"0\">".concat(constants/* Constants.ZWSP */.g.ZWSP, "<wbr></p>"));
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
        }
        else {
            range.selectNodeContents(previousElement);
            range.collapse(false);
            (0,selection/* setSelectionFocus */.Hc)(range);
        }
        event.preventDefault();
        return true;
    }
    return false;
};
var listToggle = function (vditor, range, type, cancel) {
    if (cancel === void 0) { cancel = true; }
    var itemElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "LI");
    vditor[vditor.currentMode].element.querySelectorAll("wbr").forEach(function (wbr) {
        wbr.remove();
    });
    range.insertNode(document.createElement("wbr"));
    if (cancel && itemElement) {
        // 取消
        var pHTML = "";
        for (var i = 0; i < itemElement.parentElement.childElementCount; i++) {
            var inputElement = itemElement.parentElement.children[i].querySelector("input");
            if (inputElement) {
                inputElement.remove();
            }
            pHTML += "<p data-block=\"0\">".concat(itemElement.parentElement.children[i].innerHTML.trimLeft(), "</p>");
        }
        itemElement.parentElement.insertAdjacentHTML("beforebegin", pHTML);
        itemElement.parentElement.remove();
    }
    else {
        if (!itemElement) {
            // 添加
            var blockElement = (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-block", "0");
            if (!blockElement) {
                vditor[vditor.currentMode].element.querySelector("wbr").remove();
                blockElement = vditor[vditor.currentMode].element.querySelector("p");
                blockElement.innerHTML = "<wbr>";
            }
            if (type === "check") {
                blockElement.insertAdjacentHTML("beforebegin", "<ul data-block=\"0\"><li class=\"vditor-task\"><input type=\"checkbox\" /> ".concat(blockElement.innerHTML, "</li></ul>"));
                blockElement.remove();
            }
            else if (type === "list") {
                blockElement.insertAdjacentHTML("beforebegin", "<ul data-block=\"0\"><li>".concat(blockElement.innerHTML, "</li></ul>"));
                blockElement.remove();
            }
            else if (type === "ordered-list") {
                blockElement.insertAdjacentHTML("beforebegin", "<ol data-block=\"0\"><li>".concat(blockElement.innerHTML, "</li></ol>"));
                blockElement.remove();
            }
        }
        else {
            // 切换
            if (type === "check") {
                itemElement.parentElement.querySelectorAll("li").forEach(function (item) {
                    item.insertAdjacentHTML("afterbegin", "<input type=\"checkbox\" />".concat(item.textContent.indexOf(" ") === 0 ? "" : " "));
                    item.classList.add("vditor-task");
                });
            }
            else {
                if (itemElement.querySelector("input")) {
                    itemElement.parentElement.querySelectorAll("li").forEach(function (item) {
                        item.querySelector("input").remove();
                        item.classList.remove("vditor-task");
                    });
                }
                var element = void 0;
                if (type === "list") {
                    element = document.createElement("ul");
                    element.setAttribute("data-marker", "*");
                }
                else {
                    element = document.createElement("ol");
                    element.setAttribute("data-marker", "1.");
                }
                element.setAttribute("data-block", "0");
                element.setAttribute("data-tight", itemElement.parentElement.getAttribute("data-tight"));
                element.innerHTML = itemElement.parentElement.innerHTML;
                itemElement.parentElement.parentNode.replaceChild(element, itemElement.parentElement);
            }
        }
    }
};
var listIndent = function (vditor, liElement, range) {
    var previousElement = liElement.previousElementSibling;
    if (liElement && previousElement) {
        var liElements_1 = [liElement];
        Array.from(range.cloneContents().children).forEach(function (item, index) {
            if (item.nodeType !== 3 && liElement && item.textContent.trim() !== ""
                && liElement.getAttribute("data-node-id") === item.getAttribute("data-node-id")) {
                if (index !== 0) {
                    liElements_1.push(liElement);
                }
                liElement = liElement.nextElementSibling;
            }
        });
        vditor[vditor.currentMode].element.querySelectorAll("wbr").forEach(function (wbr) {
            wbr.remove();
        });
        range.insertNode(document.createElement("wbr"));
        var liParentElement = previousElement.parentElement;
        var liHTML_1 = "";
        liElements_1.forEach(function (item) {
            var marker = item.getAttribute("data-marker");
            if (marker.length !== 1) {
                marker = "1".concat(marker.slice(-1));
            }
            liHTML_1 += "<li data-node-id=\"".concat(item.getAttribute("data-node-id"), "\" data-marker=\"").concat(marker, "\">").concat(item.innerHTML, "</li>");
            item.remove();
        });
        previousElement.insertAdjacentHTML("beforeend", "<".concat(liParentElement.tagName, " data-block=\"0\">").concat(liHTML_1, "</").concat(liParentElement.tagName, ">"));
        if (vditor.currentMode === "wysiwyg") {
            liParentElement.outerHTML = vditor.lute.SpinVditorDOM(liParentElement.outerHTML);
        }
        else {
            liParentElement.outerHTML = vditor.lute.SpinVditorIRDOM(liParentElement.outerHTML);
        }
        (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
        var tempTopListElement = (0,hasClosest/* getTopList */.O9)(range.startContainer);
        if (tempTopListElement) {
            tempTopListElement.querySelectorAll(".vditor-".concat(vditor.currentMode, "__preview[data-render='2']"))
                .forEach(function (item) {
                processCodeRender(item, vditor);
                if (vditor.currentMode === "wysiwyg") {
                    item.previousElementSibling.setAttribute("style", "display:none");
                }
            });
        }
        execAfterRender(vditor);
        highlightToolbar(vditor);
    }
    else {
        vditor[vditor.currentMode].element.focus();
    }
};
var listOutdent = function (vditor, liElement, range, topListElement) {
    var liParentLiElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(liElement.parentElement, "LI");
    if (liParentLiElement) {
        vditor[vditor.currentMode].element.querySelectorAll("wbr").forEach(function (wbr) {
            wbr.remove();
        });
        range.insertNode(document.createElement("wbr"));
        var liParentElement = liElement.parentElement;
        var liParentAfterElement = liParentElement.cloneNode();
        var liElements_2 = [liElement];
        Array.from(range.cloneContents().children).forEach(function (item, index) {
            if (item.nodeType !== 3 && liElement && item.textContent.trim() !== "" &&
                liElement.getAttribute("data-node-id") === item.getAttribute("data-node-id")) {
                if (index !== 0) {
                    liElements_2.push(liElement);
                }
                liElement = liElement.nextElementSibling;
            }
        });
        var isMatch_1 = false;
        var afterHTML_1 = "";
        liParentElement.querySelectorAll("li").forEach(function (item) {
            if (isMatch_1) {
                afterHTML_1 += item.outerHTML;
                if (!item.nextElementSibling && !item.previousElementSibling) {
                    item.parentElement.remove();
                }
                else {
                    item.remove();
                }
            }
            if (item.isSameNode(liElements_2[liElements_2.length - 1])) {
                isMatch_1 = true;
            }
        });
        liElements_2.reverse().forEach(function (item) {
            liParentLiElement.insertAdjacentElement("afterend", item);
        });
        if (afterHTML_1) {
            liParentAfterElement.innerHTML = afterHTML_1;
            liElements_2[0].insertAdjacentElement("beforeend", liParentAfterElement);
        }
        if (vditor.currentMode === "wysiwyg") {
            topListElement.outerHTML = vditor.lute.SpinVditorDOM(topListElement.outerHTML);
        }
        else {
            topListElement.outerHTML = vditor.lute.SpinVditorIRDOM(topListElement.outerHTML);
        }
        (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
        var tempTopListElement = (0,hasClosest/* getTopList */.O9)(range.startContainer);
        if (tempTopListElement) {
            tempTopListElement.querySelectorAll(".vditor-".concat(vditor.currentMode, "__preview[data-render='2']"))
                .forEach(function (item) {
                processCodeRender(item, vditor);
                if (vditor.currentMode === "wysiwyg") {
                    item.previousElementSibling.setAttribute("style", "display:none");
                }
            });
        }
        execAfterRender(vditor);
        highlightToolbar(vditor);
    }
    else {
        vditor[vditor.currentMode].element.focus();
    }
};
var setTableAlign = function (tableElement, type) {
    var cell = getSelection().getRangeAt(0).startContainer.parentElement;
    var columnCnt = tableElement.rows[0].cells.length;
    var rowCnt = tableElement.rows.length;
    var currentColumn = 0;
    for (var i = 0; i < rowCnt; i++) {
        for (var j = 0; j < columnCnt; j++) {
            if (tableElement.rows[i].cells[j].isSameNode(cell)) {
                currentColumn = j;
                break;
            }
        }
    }
    for (var k = 0; k < rowCnt; k++) {
        tableElement.rows[k].cells[currentColumn].setAttribute("align", type);
    }
};
var isHrMD = function (text) {
    // - _ *
    var marker = text.trimRight().split("\n").pop();
    if (marker === "") {
        return false;
    }
    if (marker.replace(/ |-/g, "") === ""
        || marker.replace(/ |_/g, "") === ""
        || marker.replace(/ |\*/g, "") === "") {
        if (marker.replace(/ /g, "").length > 2) {
            if (marker.indexOf("-") > -1 && marker.trimLeft().indexOf(" ") === -1
                && text.trimRight().split("\n").length > 1) {
                // 满足 heading
                return false;
            }
            if (marker.indexOf("    ") === 0 || marker.indexOf("\t") === 0) {
                // 代码块
                return false;
            }
            return true;
        }
        return false;
    }
    return false;
};
var isHeadingMD = function (text) {
    // - =
    var textArray = text.trimRight().split("\n");
    text = textArray.pop();
    if (text.indexOf("    ") === 0 || text.indexOf("\t") === 0) {
        return false;
    }
    text = text.trimLeft();
    if (text === "" || textArray.length === 0) {
        return false;
    }
    if (text.replace(/-/g, "") === ""
        || text.replace(/=/g, "") === "") {
        return true;
    }
    return false;
};
var execAfterRender = function (vditor, options) {
    if (options === void 0) { options = {
        enableAddUndoStack: true,
        enableHint: false,
        enableInput: true,
    }; }
    if (vditor.currentMode === "wysiwyg") {
        afterRenderEvent(vditor, options);
    }
    else if (vditor.currentMode === "ir") {
        process_processAfterRender(vditor, options);
    }
    else if (vditor.currentMode === "sv") {
        processAfterRender(vditor, options);
    }
};
var fixList = function (range, vditor, pElement, event) {
    var _a;
    var startContainer = range.startContainer;
    var liElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "LI");
    if (liElement) {
        if (!(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && event.key === "Enter" &&
            // fix li 中有多个 P 时，在第一个 P 中换行会在下方生成新的 li
            (!event.shiftKey && pElement && liElement.contains(pElement) && pElement.nextElementSibling)) {
            if (liElement && !liElement.textContent.endsWith("\n")) {
                // li 结尾需 \n
                liElement.insertAdjacentText("beforeend", "\n");
            }
            range.insertNode(document.createTextNode("\n\n"));
            range.collapse(false);
            execAfterRender(vditor);
            event.preventDefault();
            return true;
        }
        if (!(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey && event.key === "Backspace" &&
            !liElement.previousElementSibling && range.toString() === "" &&
            (0,selection/* getSelectPosition */.im)(liElement, vditor[vditor.currentMode].element, range).start === 0) {
            // 光标位于点和第一个字符中间时，无法删除 li 元素
            if (liElement.nextElementSibling) {
                liElement.parentElement.insertAdjacentHTML("beforebegin", "<p data-block=\"0\"><wbr>".concat(liElement.innerHTML, "</p>"));
                liElement.remove();
            }
            else {
                liElement.parentElement.outerHTML = "<p data-block=\"0\"><wbr>".concat(liElement.innerHTML, "</p>");
            }
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            event.preventDefault();
            return true;
        }
        // 空列表删除后与上一级段落对齐
        if (!(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey && event.key === "Backspace" &&
            liElement.textContent.trim().replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "" &&
            range.toString() === "" && ((_a = liElement.previousElementSibling) === null || _a === void 0 ? void 0 : _a.tagName) === "LI") {
            liElement.previousElementSibling.insertAdjacentText("beforeend", "\n\n");
            range.selectNodeContents(liElement.previousElementSibling);
            range.collapse(false);
            liElement.remove();
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            event.preventDefault();
            return true;
        }
        if (!(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && event.key === "Tab") {
            // 光标位于第一/零字符时，tab 用于列表的缩进
            var isFirst = false;
            if (range.startOffset === 0
                && ((startContainer.nodeType === 3 && !startContainer.previousSibling)
                    || (startContainer.nodeType !== 3 && startContainer.nodeName === "LI"))) {
                // 有序/无序列表
                isFirst = true;
            }
            else if (liElement.classList.contains("vditor-task") && range.startOffset === 1
                && startContainer.previousSibling.nodeType !== 3
                && startContainer.previousSibling.tagName === "INPUT") {
                // 任务列表
                isFirst = true;
            }
            if (isFirst || range.toString() !== "") {
                if (event.shiftKey) {
                    listOutdent(vditor, liElement, range, liElement.parentElement);
                }
                else {
                    listIndent(vditor, liElement, range);
                }
                event.preventDefault();
                return true;
            }
        }
    }
    return false;
};
// tab 处理: block code render, table, 列表第一个字符中的 tab 处理单独写在上面
var fixTab = function (vditor, range, event) {
    if (vditor.options.tab && event.key === "Tab") {
        if (event.shiftKey) {
            // TODO shift+tab
        }
        else {
            if (range.toString() === "") {
                range.insertNode(document.createTextNode(vditor.options.tab));
                range.collapse(false);
            }
            else {
                range.extractContents();
                range.insertNode(document.createTextNode(vditor.options.tab));
                range.collapse(false);
            }
        }
        (0,selection/* setSelectionFocus */.Hc)(range);
        execAfterRender(vditor);
        event.preventDefault();
        return true;
    }
};
var fixMarkdown = function (event, vditor, pElement, range) {
    if (!pElement) {
        return;
    }
    if (!(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && event.key === "Enter") {
        var pText = String.raw(templateObject_1 || (templateObject_1 = __makeTemplateObject(["", ""], ["", ""])), pElement.textContent).replace(/\\\|/g, "").trim();
        var pTextList = pText.split("|");
        if (pText.startsWith("|") && pText.endsWith("|") && pTextList.length > 3) {
            // table 自动完成
            var tableHeaderMD = pTextList.map(function () { return "---"; }).join("|");
            tableHeaderMD =
                pElement.textContent + "\n" + tableHeaderMD.substring(3, tableHeaderMD.length - 3) + "\n|<wbr>";
            pElement.outerHTML = vditor.lute.SpinVditorDOM(tableHeaderMD);
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            scrollCenter(vditor);
            event.preventDefault();
            return true;
        }
        // hr 渲染
        if (isHrMD(pElement.innerHTML) && pElement.previousElementSibling) {
            // 软换行后 hr 前有内容
            var pInnerHTML = "";
            var innerHTMLList = pElement.innerHTML.trimRight().split("\n");
            if (innerHTMLList.length > 1) {
                innerHTMLList.pop();
                pInnerHTML = "<p data-block=\"0\">".concat(innerHTMLList.join("\n"), "</p>");
            }
            pElement.insertAdjacentHTML("afterend", "".concat(pInnerHTML, "<hr data-block=\"0\"><p data-block=\"0\"><wbr>\n</p>"));
            pElement.remove();
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            scrollCenter(vditor);
            event.preventDefault();
            return true;
        }
        if (isHeadingMD(pElement.innerHTML)) {
            // heading 渲染
            if (vditor.currentMode === "wysiwyg") {
                pElement.outerHTML = vditor.lute.SpinVditorDOM(pElement.innerHTML + '<p data-block="0"><wbr>\n</p>');
            }
            else {
                pElement.outerHTML = vditor.lute.SpinVditorIRDOM(pElement.innerHTML + '<p data-block="0"><wbr>\n</p>');
            }
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            scrollCenter(vditor);
            event.preventDefault();
            return true;
        }
    }
    // 软换行会被切割 https://github.com/Vanessa219/vditor/issues/220
    if (range.collapsed && pElement.previousElementSibling && event.key === "Backspace" &&
        !(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && !event.shiftKey &&
        pElement.textContent.trimRight().split("\n").length > 1 &&
        (0,selection/* getSelectPosition */.im)(pElement, vditor[vditor.currentMode].element, range).start === 0) {
        var lastElement = (0,hasClosest/* getLastNode */.DX)(pElement.previousElementSibling);
        if (!lastElement.textContent.endsWith("\n")) {
            lastElement.textContent = lastElement.textContent + "\n";
        }
        lastElement.parentElement.insertAdjacentHTML("beforeend", "<wbr>".concat(pElement.innerHTML));
        pElement.remove();
        (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
        return false;
    }
    return false;
};
var insertRow = function (vditor, range, cellElement) {
    var rowHTML = "";
    for (var m = 0; m < cellElement.parentElement.childElementCount; m++) {
        rowHTML += "<td align=\"".concat(cellElement.parentElement.children[m].getAttribute("align"), "\"> </td>");
    }
    if (cellElement.tagName === "TH") {
        cellElement.parentElement.parentElement.insertAdjacentHTML("afterend", "<tbody><tr>".concat(rowHTML, "</tr></tbody>"));
    }
    else {
        cellElement.parentElement.insertAdjacentHTML("afterend", "<tr>".concat(rowHTML, "</tr>"));
    }
    execAfterRender(vditor);
};
var insertRowAbove = function (vditor, range, cellElement) {
    var rowHTML = "";
    for (var m = 0; m < cellElement.parentElement.childElementCount; m++) {
        if (cellElement.tagName === "TH") {
            rowHTML += "<th align=\"".concat(cellElement.parentElement.children[m].getAttribute("align"), "\"> </th>");
        }
        else {
            rowHTML += "<td align=\"".concat(cellElement.parentElement.children[m].getAttribute("align"), "\"> </td>");
        }
    }
    if (cellElement.tagName === "TH") {
        cellElement.parentElement.parentElement.insertAdjacentHTML("beforebegin", "<thead><tr>".concat(rowHTML, "</tr></thead>"));
        range.insertNode(document.createElement("wbr"));
        var theadHTML = cellElement.parentElement.innerHTML.replace(/<th>/g, "<td>").replace(/<\/th>/g, "</td>");
        cellElement.parentElement.parentElement.nextElementSibling.insertAdjacentHTML("afterbegin", theadHTML);
        cellElement.parentElement.parentElement.remove();
        (0,selection/* setRangeByWbr */.ib)(vditor.ir.element, range);
    }
    else {
        cellElement.parentElement.insertAdjacentHTML("beforebegin", "<tr>".concat(rowHTML, "</tr>"));
    }
    execAfterRender(vditor);
};
var insertColumn = function (vditor, tableElement, cellElement, type) {
    if (type === void 0) { type = "afterend"; }
    var index = 0;
    var previousElement = cellElement.previousElementSibling;
    while (previousElement) {
        index++;
        previousElement = previousElement.previousElementSibling;
    }
    for (var i = 0; i < tableElement.rows.length; i++) {
        if (i === 0) {
            tableElement.rows[i].cells[index].insertAdjacentHTML(type, "<th> </th>");
        }
        else {
            tableElement.rows[i].cells[index].insertAdjacentHTML(type, "<td> </td>");
        }
    }
    execAfterRender(vditor);
};
var deleteRow = function (vditor, range, cellElement) {
    if (cellElement.tagName === "TD") {
        var tbodyElement = cellElement.parentElement.parentElement;
        if (cellElement.parentElement.previousElementSibling) {
            range.selectNodeContents(cellElement.parentElement.previousElementSibling.lastElementChild);
        }
        else {
            range.selectNodeContents(tbodyElement.previousElementSibling.lastElementChild.lastElementChild);
        }
        if (tbodyElement.childElementCount === 1) {
            tbodyElement.remove();
        }
        else {
            cellElement.parentElement.remove();
        }
        range.collapse(false);
        (0,selection/* setSelectionFocus */.Hc)(range);
        execAfterRender(vditor);
    }
};
var deleteColumn = function (vditor, range, tableElement, cellElement) {
    var index = 0;
    var previousElement = cellElement.previousElementSibling;
    while (previousElement) {
        index++;
        previousElement = previousElement.previousElementSibling;
    }
    if (cellElement.previousElementSibling || cellElement.nextElementSibling) {
        range.selectNodeContents(cellElement.previousElementSibling || cellElement.nextElementSibling);
        range.collapse(true);
    }
    for (var i = 0; i < tableElement.rows.length; i++) {
        var cells = tableElement.rows[i].cells;
        if (cells.length === 1) {
            tableElement.remove();
            highlightToolbar(vditor);
            break;
        }
        cells[index].remove();
    }
    (0,selection/* setSelectionFocus */.Hc)(range);
    execAfterRender(vditor);
};
var fixTable = function (vditor, event, range) {
    var startContainer = range.startContainer;
    var cellElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TD") ||
        (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "TH");
    if (cellElement) {
        // 换行或软换行：在 cell 中添加 br
        if (!(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && event.key === "Enter") {
            if (!cellElement.lastElementChild ||
                (cellElement.lastElementChild && (!cellElement.lastElementChild.isSameNode(cellElement.lastChild) ||
                    cellElement.lastElementChild.tagName !== "BR"))) {
                cellElement.insertAdjacentHTML("beforeend", "<br>");
            }
            var brElement = document.createElement("br");
            range.insertNode(brElement);
            range.setStartAfter(brElement);
            execAfterRender(vditor);
            scrollCenter(vditor);
            event.preventDefault();
            return true;
        }
        // tab：光标移向下一个 cell
        if (event.key === "Tab") {
            if (event.shiftKey) {
                // shift + tab 光标移动到前一个 cell
                goPreviousCell(cellElement, range);
                event.preventDefault();
                return true;
            }
            var nextElement = cellElement.nextElementSibling;
            if (!nextElement) {
                if (cellElement.parentElement.nextElementSibling) {
                    nextElement = cellElement.parentElement.nextElementSibling.firstElementChild;
                }
                else if (cellElement.parentElement.parentElement.tagName === "THEAD" &&
                    cellElement.parentElement.parentElement.nextElementSibling) {
                    nextElement =
                        cellElement.parentElement.parentElement.nextElementSibling.firstElementChild.firstElementChild;
                }
                else {
                    nextElement = null;
                }
            }
            if (nextElement) {
                range.selectNodeContents(nextElement);
                (0,selection/* setSelectionFocus */.Hc)(range);
            }
            event.preventDefault();
            return true;
        }
        var tableElement = cellElement.parentElement.parentElement.parentElement;
        if (event.key === "ArrowUp") {
            event.preventDefault();
            if (cellElement.tagName === "TH") {
                if (tableElement.previousElementSibling) {
                    range.selectNodeContents(tableElement.previousElementSibling);
                    range.collapse(false);
                    (0,selection/* setSelectionFocus */.Hc)(range);
                }
                else {
                    insertEmptyBlock(vditor, "beforebegin");
                }
                return true;
            }
            var m = 0;
            var trElement = cellElement.parentElement;
            for (; m < trElement.cells.length; m++) {
                if (trElement.cells[m].isSameNode(cellElement)) {
                    break;
                }
            }
            var previousElement = trElement.previousElementSibling;
            if (!previousElement) {
                previousElement = trElement.parentElement.previousElementSibling.firstChild;
            }
            range.selectNodeContents(previousElement.cells[m]);
            range.collapse(false);
            (0,selection/* setSelectionFocus */.Hc)(range);
            return true;
        }
        if (event.key === "ArrowDown") {
            event.preventDefault();
            var trElement = cellElement.parentElement;
            if (!trElement.nextElementSibling && cellElement.tagName === "TD") {
                if (tableElement.nextElementSibling) {
                    range.selectNodeContents(tableElement.nextElementSibling);
                    range.collapse(true);
                    (0,selection/* setSelectionFocus */.Hc)(range);
                }
                else {
                    insertEmptyBlock(vditor, "afterend");
                }
                return true;
            }
            var m = 0;
            for (; m < trElement.cells.length; m++) {
                if (trElement.cells[m].isSameNode(cellElement)) {
                    break;
                }
            }
            var nextElement = trElement.nextElementSibling;
            if (!nextElement) {
                nextElement = trElement.parentElement.nextElementSibling.firstChild;
            }
            range.selectNodeContents(nextElement.cells[m]);
            range.collapse(true);
            (0,selection/* setSelectionFocus */.Hc)(range);
            return true;
        }
        // focus row input, only wysiwyg
        if (vditor.currentMode === "wysiwyg" &&
            !(0,compatibility/* isCtrl */.yl)(event) && event.key === "Enter" && !event.shiftKey && event.altKey) {
            var inputElement = vditor.wysiwyg.popover.querySelector(".vditor-input");
            inputElement.focus();
            inputElement.select();
            event.preventDefault();
            return true;
        }
        // Backspace：光标移动到前一个 cell
        if (!(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey && event.key === "Backspace"
            && range.startOffset === 0 && range.toString() === "") {
            var previousCellElement = goPreviousCell(cellElement, range, false);
            if (!previousCellElement && tableElement) {
                if (tableElement.textContent.trim() === "") {
                    tableElement.outerHTML = "<p data-block=\"0\"><wbr>\n</p>";
                    (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
                }
                else {
                    range.setStartBefore(tableElement);
                    range.collapse(true);
                }
                execAfterRender(vditor);
            }
            event.preventDefault();
            return true;
        }
        // 上方新添加一行
        if (matchHotKey("⇧⌘F", event)) {
            insertRowAbove(vditor, range, cellElement);
            event.preventDefault();
            return true;
        }
        // 下方新添加一行 https://github.com/Vanessa219/vditor/issues/46
        if (matchHotKey("⌘=", event)) {
            insertRow(vditor, range, cellElement);
            event.preventDefault();
            return true;
        }
        // 左方新添加一列
        if (matchHotKey("⇧⌘G", event)) {
            insertColumn(vditor, tableElement, cellElement, "beforebegin");
            event.preventDefault();
            return true;
        }
        // 后方新添加一列
        if (matchHotKey("⇧⌘=", event)) {
            insertColumn(vditor, tableElement, cellElement);
            event.preventDefault();
            return true;
        }
        // 删除当前行
        if (matchHotKey("⌘-", event)) {
            deleteRow(vditor, range, cellElement);
            event.preventDefault();
            return true;
        }
        // 删除当前列
        if (matchHotKey("⇧⌘-", event)) {
            deleteColumn(vditor, range, tableElement, cellElement);
            event.preventDefault();
            return true;
        }
        // 剧左
        if (matchHotKey("⇧⌘L", event)) {
            if (vditor.currentMode === "ir") {
                setTableAlign(tableElement, "left");
                execAfterRender(vditor);
                event.preventDefault();
                return true;
            }
            else {
                var itemElement = vditor.wysiwyg.popover.querySelector('[data-type="left"]');
                if (itemElement) {
                    itemElement.click();
                    event.preventDefault();
                    return true;
                }
            }
        }
        // 剧中
        if (matchHotKey("⇧⌘C", event)) {
            if (vditor.currentMode === "ir") {
                setTableAlign(tableElement, "center");
                execAfterRender(vditor);
                event.preventDefault();
                return true;
            }
            else {
                var itemElement = vditor.wysiwyg.popover.querySelector('[data-type="center"]');
                if (itemElement) {
                    itemElement.click();
                    event.preventDefault();
                    return true;
                }
            }
        }
        // 剧右
        if (matchHotKey("⇧⌘R", event)) {
            if (vditor.currentMode === "ir") {
                setTableAlign(tableElement, "right");
                execAfterRender(vditor);
                event.preventDefault();
                return true;
            }
            else {
                var itemElement = vditor.wysiwyg.popover.querySelector('[data-type="right"]');
                if (itemElement) {
                    itemElement.click();
                    event.preventDefault();
                    return true;
                }
            }
        }
    }
    return false;
};
var fixCodeBlock = function (vditor, event, codeRenderElement, range) {
    // 行级代码块中 command + a，近对当前代码块进行全选
    if (codeRenderElement.tagName === "PRE" && matchHotKey("⌘A", event)) {
        range.selectNodeContents(codeRenderElement.firstElementChild);
        event.preventDefault();
        return true;
    }
    // tab
    // TODO shift + tab, shift and 选中文字
    if (vditor.options.tab && event.key === "Tab" && !event.shiftKey && range.toString() === "") {
        range.insertNode(document.createTextNode(vditor.options.tab));
        range.collapse(false);
        execAfterRender(vditor);
        event.preventDefault();
        return true;
    }
    // Backspace: 光标位于第零个字符，仅删除代码块标签
    if (event.key === "Backspace" && !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey) {
        var codePosition = (0,selection/* getSelectPosition */.im)(codeRenderElement, vditor[vditor.currentMode].element, range);
        if ((codePosition.start === 0 ||
            (codePosition.start === 1 && codeRenderElement.innerText === "\n")) // 空代码块，光标在 \n 后
            && range.toString() === "") {
            codeRenderElement.parentElement.outerHTML =
                "<p data-block=\"0\"><wbr>".concat(codeRenderElement.firstElementChild.innerHTML, "</p>");
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            event.preventDefault();
            return true;
        }
    }
    // 换行
    if (!(0,compatibility/* isCtrl */.yl)(event) && !event.altKey && event.key === "Enter") {
        if (!codeRenderElement.firstElementChild.textContent.endsWith("\n")) {
            codeRenderElement.firstElementChild.insertAdjacentText("beforeend", "\n");
        }
        range.extractContents();
        range.insertNode(document.createTextNode("\n"));
        range.collapse(false);
        (0,selection/* setSelectionFocus */.Hc)(range);
        if (!(0,compatibility/* isFirefox */.vU)()) {
            if (vditor.currentMode === "wysiwyg") {
                input_input(vditor, range);
            }
            else {
                input(vditor, range);
            }
        }
        scrollCenter(vditor);
        event.preventDefault();
        return true;
    }
    return false;
};
var fixBlockquote = function (vditor, range, event, pElement) {
    var startContainer = range.startContainer;
    var blockquoteElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(startContainer, "BLOCKQUOTE");
    if (blockquoteElement && range.toString() === "") {
        if (event.key === "Backspace" && !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey &&
            (0,selection/* getSelectPosition */.im)(blockquoteElement, vditor[vditor.currentMode].element, range).start === 0) {
            // Backspace: 光标位于引用中的第零个字符，仅删除引用标签
            range.insertNode(document.createElement("wbr"));
            blockquoteElement.outerHTML = blockquoteElement.innerHTML;
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            event.preventDefault();
            return true;
        }
        if (pElement && event.key === "Enter" && !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey
            && pElement.parentElement.tagName === "BLOCKQUOTE") {
            // Enter: 空行回车应逐层跳出
            var isEmpty = false;
            if (pElement.innerHTML.replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "\n" ||
                pElement.innerHTML.replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "") {
                // 空 P
                isEmpty = true;
                pElement.remove();
            }
            else if (pElement.innerHTML.endsWith("\n\n") &&
                (0,selection/* getSelectPosition */.im)(pElement, vditor[vditor.currentMode].element, range).start ===
                    pElement.textContent.length - 1) {
                // 软换行
                pElement.innerHTML = pElement.innerHTML.substr(0, pElement.innerHTML.length - 2);
                isEmpty = true;
            }
            if (isEmpty) {
                // 需添加零宽字符，否则的话无法记录 undo
                blockquoteElement.insertAdjacentHTML("afterend", "<p data-block=\"0\">".concat(constants/* Constants.ZWSP */.g.ZWSP, "<wbr>\n</p>"));
                (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
                execAfterRender(vditor);
                event.preventDefault();
                return true;
            }
        }
        var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(startContainer);
        if (vditor.currentMode === "wysiwyg" && blockElement && matchHotKey("⇧⌘;", event)) {
            // 插入 blockquote
            range.insertNode(document.createElement("wbr"));
            blockElement.outerHTML = "<blockquote data-block=\"0\">".concat(blockElement.outerHTML, "</blockquote>");
            (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
            afterRenderEvent(vditor);
            event.preventDefault();
            return true;
        }
        if (insertAfterBlock(vditor, event, range, blockquoteElement, blockquoteElement)) {
            return true;
        }
        if (insertBeforeBlock(vditor, event, range, blockquoteElement, blockquoteElement)) {
            return true;
        }
    }
    return false;
};
var fixTask = function (vditor, range, event) {
    var startContainer = range.startContainer;
    var taskItemElement = (0,hasClosest/* hasClosestByClassName */.fb)(startContainer, "vditor-task");
    if (taskItemElement) {
        if (matchHotKey("⇧⌘J", event)) {
            // ctrl + shift: toggle checked
            var inputElement = taskItemElement.firstElementChild;
            if (inputElement.checked) {
                inputElement.removeAttribute("checked");
            }
            else {
                inputElement.setAttribute("checked", "checked");
            }
            execAfterRender(vditor);
            event.preventDefault();
            return true;
        }
        // Backspace: 在选择框前进行删除
        if (event.key === "Backspace" && !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey && range.toString() === ""
            && range.startOffset === 1
            && ((startContainer.nodeType === 3 && startContainer.previousSibling &&
                startContainer.previousSibling.tagName === "INPUT")
                || startContainer.nodeType !== 3)) {
            var previousElement = taskItemElement.previousElementSibling;
            taskItemElement.querySelector("input").remove();
            if (previousElement) {
                var lastNode = (0,hasClosest/* getLastNode */.DX)(previousElement);
                lastNode.parentElement.insertAdjacentHTML("beforeend", "<wbr>" + taskItemElement.innerHTML.trim());
                taskItemElement.remove();
            }
            else {
                taskItemElement.parentElement.insertAdjacentHTML("beforebegin", "<p data-block=\"0\"><wbr>".concat(taskItemElement.innerHTML.trim() || "\n", "</p>"));
                if (taskItemElement.nextElementSibling) {
                    taskItemElement.remove();
                }
                else {
                    taskItemElement.parentElement.remove();
                }
            }
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            event.preventDefault();
            return true;
        }
        if (event.key === "Enter" && !(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey) {
            if (taskItemElement.textContent.trim() === "") {
                // 当前任务列表无文字
                if ((0,hasClosest/* hasClosestByClassName */.fb)(taskItemElement.parentElement, "vditor-task")) {
                    // 为子元素时，需进行反向缩进
                    var topListElement = (0,hasClosest/* getTopList */.O9)(startContainer);
                    if (topListElement) {
                        listOutdent(vditor, taskItemElement, range, topListElement);
                    }
                }
                else {
                    // 仅有一级任务列表
                    if (taskItemElement.nextElementSibling) {
                        // 任务列表下方还有元素，需要使用用段落隔断
                        var afterHTML_2 = "";
                        var beforeHTML_1 = "";
                        var isAfter_1 = false;
                        Array.from(taskItemElement.parentElement.children).forEach(function (taskItem) {
                            if (taskItemElement.isSameNode(taskItem)) {
                                isAfter_1 = true;
                            }
                            else {
                                if (isAfter_1) {
                                    afterHTML_2 += taskItem.outerHTML;
                                }
                                else {
                                    beforeHTML_1 += taskItem.outerHTML;
                                }
                            }
                        });
                        var parentTagName = taskItemElement.parentElement.tagName;
                        var dataMarker = taskItemElement.parentElement.tagName === "OL" ? "" : " data-marker=\"".concat(taskItemElement.parentElement.getAttribute("data-marker"), "\"");
                        var startAttribute = "";
                        if (beforeHTML_1) {
                            startAttribute = taskItemElement.parentElement.tagName === "UL" ? "" : " start=\"1\"";
                            beforeHTML_1 = "<".concat(parentTagName, " data-tight=\"true\"").concat(dataMarker, " data-block=\"0\">").concat(beforeHTML_1, "</").concat(parentTagName, ">");
                        }
                        // <p data-block="0">\n<wbr></p> => <p data-block="0"><wbr>\n</p>
                        // https://github.com/Vanessa219/vditor/issues/430
                        taskItemElement.parentElement.outerHTML = "".concat(beforeHTML_1, "<p data-block=\"0\"><wbr>\n</p><").concat(parentTagName, "\n data-tight=\"true\"").concat(dataMarker, " data-block=\"0\"").concat(startAttribute, ">").concat(afterHTML_2, "</").concat(parentTagName, ">");
                    }
                    else {
                        // 任务列表下方无任务列表元素
                        taskItemElement.parentElement.insertAdjacentHTML("afterend", "<p data-block=\"0\"><wbr>\n</p>");
                        if (taskItemElement.parentElement.querySelectorAll("li").length === 1) {
                            // 任务列表仅有一项时，使用 p 元素替换
                            taskItemElement.parentElement.remove();
                        }
                        else {
                            // 任务列表有多项时，当前任务列表位于最后一项，移除该任务列表
                            taskItemElement.remove();
                        }
                    }
                }
            }
            else if (startContainer.nodeType !== 3 && range.startOffset === 0 &&
                startContainer.firstChild.tagName === "INPUT") {
                // 光标位于 input 之前
                range.setStart(startContainer.childNodes[1], 1);
            }
            else {
                // 当前任务列表有文字，光标后的文字需添加到新任务列表中
                range.setEndAfter(taskItemElement.lastChild);
                taskItemElement.insertAdjacentHTML("afterend", "<li class=\"vditor-task\" data-marker=\"".concat(taskItemElement.getAttribute("data-marker"), "\"><input type=\"checkbox\"> <wbr></li>"));
                document.querySelector("wbr").after(range.extractContents());
            }
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            scrollCenter(vditor);
            event.preventDefault();
            return true;
        }
    }
    return false;
};
var fixDelete = function (vditor, range, event, pElement) {
    if (range.startContainer.nodeType !== 3) {
        // 光标位于 hr 前，hr 前有内容
        var rangeElement = range.startContainer.children[range.startOffset];
        if (rangeElement && rangeElement.tagName === "HR") {
            range.selectNodeContents(rangeElement.previousElementSibling);
            range.collapse(false);
            event.preventDefault();
            return true;
        }
    }
    if (pElement) {
        var previousElement = pElement.previousElementSibling;
        if (previousElement && (0,selection/* getSelectPosition */.im)(pElement, vditor[vditor.currentMode].element, range).start === 0 &&
            (((0,compatibility/* isFirefox */.vU)() && previousElement.tagName === "HR") || previousElement.tagName === "TABLE")) {
            if (previousElement.tagName === "TABLE") {
                // table 后删除 https://github.com/Vanessa219/vditor/issues/243
                var lastCellElement = previousElement.lastElementChild.lastElementChild.lastElementChild;
                lastCellElement.innerHTML =
                    lastCellElement.innerHTML.trimLeft() + "<wbr>" + pElement.textContent.trim();
                pElement.remove();
            }
            else {
                // 光标位于 hr 后进行删除
                previousElement.remove();
            }
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
            execAfterRender(vditor);
            event.preventDefault();
            return true;
        }
    }
    return false;
};
var fixHR = function (range) {
    if ((0,compatibility/* isFirefox */.vU)() && range.startContainer.nodeType !== 3 &&
        range.startContainer.tagName === "HR") {
        range.setStartBefore(range.startContainer);
    }
};
// firefox https://github.com/Vanessa219/vditor/issues/407
var fixFirefoxArrowUpTable = function (event, blockElement, range) {
    var _a, _b;
    if (!(0,compatibility/* isFirefox */.vU)()) {
        return false;
    }
    if (event.key === "ArrowUp" && blockElement && ((_a = blockElement.previousElementSibling) === null || _a === void 0 ? void 0 : _a.tagName) === "TABLE") {
        var tableElement = blockElement.previousElementSibling;
        range.selectNodeContents(tableElement.rows[tableElement.rows.length - 1].lastElementChild);
        range.collapse(false);
        event.preventDefault();
        return true;
    }
    if (event.key === "ArrowDown" && blockElement && ((_b = blockElement.nextElementSibling) === null || _b === void 0 ? void 0 : _b.tagName) === "TABLE") {
        range.selectNodeContents(blockElement.nextElementSibling.rows[0].cells[0]);
        range.collapse(true);
        event.preventDefault();
        return true;
    }
    return false;
};
var paste = function (vditor, event, callback) { return fixBrowserBehavior_awaiter(void 0, void 0, void 0, function () {
    var textHTML, textPlain, files, renderers, renderLinkDest, doc, height, code, codeElement, position, tempElement, fileReader_1, file_1, range, blockElement, range;
    var _a;
    return fixBrowserBehavior_generator(this, function (_b) {
        switch (_b.label) {
            case 0:
                if (vditor[vditor.currentMode].element.getAttribute("contenteditable") !== "true") {
                    return [2 /*return*/];
                }
                event.stopPropagation();
                event.preventDefault();
                if ("clipboardData" in event) {
                    textHTML = event.clipboardData.getData("text/html");
                    textPlain = event.clipboardData.getData("text/plain");
                    files = event.clipboardData.files;
                }
                else {
                    textHTML = event.dataTransfer.getData("text/html");
                    textPlain = event.dataTransfer.getData("text/plain");
                    if (event.dataTransfer.types.includes("Files")) {
                        files = event.dataTransfer.items;
                    }
                }
                renderers = {};
                renderLinkDest = function (node, entering) {
                    if (!entering) {
                        return ["", Lute.WalkContinue];
                    }
                    if (vditor.options.upload.renderLinkDest) {
                        return vditor.options.upload.renderLinkDest(vditor, node, entering);
                    }
                    var src = node.TokensStr();
                    if (node.__internal_object__.Parent.Type === 34 && src && src.indexOf("file://") === -1 &&
                        vditor.options.upload.linkToImgUrl) {
                        var xhr_1 = new XMLHttpRequest();
                        xhr_1.open("POST", vditor.options.upload.linkToImgUrl);
                        if (vditor.options.upload.token) {
                            xhr_1.setRequestHeader("X-Upload-Token", vditor.options.upload.token);
                        }
                        if (vditor.options.upload.withCredentials) {
                            xhr_1.withCredentials = true;
                        }
                        setHeaders(vditor, xhr_1);
                        xhr_1.setRequestHeader("Content-Type", "application/json; charset=utf-8");
                        xhr_1.onreadystatechange = function () {
                            if (xhr_1.readyState === XMLHttpRequest.DONE) {
                                if (xhr_1.status === 200) {
                                    var responseText = xhr_1.responseText;
                                    if (vditor.options.upload.linkToImgFormat) {
                                        responseText = vditor.options.upload.linkToImgFormat(xhr_1.responseText);
                                    }
                                    var responseJSON_1 = JSON.parse(responseText);
                                    if (responseJSON_1.code !== 0) {
                                        vditor.tip.show(responseJSON_1.msg);
                                        return;
                                    }
                                    var original_1 = responseJSON_1.data.originalURL;
                                    if (vditor.currentMode === "sv") {
                                        vditor.sv.element.querySelectorAll(".vditor-sv__marker--link")
                                            .forEach(function (item) {
                                            if (item.textContent === original_1) {
                                                item.textContent = responseJSON_1.data.url;
                                            }
                                        });
                                    }
                                    else {
                                        var imgElement = vditor[vditor.currentMode].element.querySelector("img[src=\"".concat(original_1, "\"]"));
                                        imgElement.src = responseJSON_1.data.url;
                                        if (vditor.currentMode === "ir") {
                                            imgElement.previousElementSibling.previousElementSibling.innerHTML =
                                                responseJSON_1.data.url;
                                        }
                                    }
                                    execAfterRender(vditor);
                                }
                                else {
                                    vditor.tip.show(xhr_1.responseText);
                                }
                                if (vditor.options.upload.linkToImgCallback) {
                                    vditor.options.upload.linkToImgCallback(xhr_1.responseText);
                                }
                            }
                        };
                        xhr_1.send(JSON.stringify({ url: src }));
                    }
                    if (vditor.currentMode === "ir") {
                        return ["<span class=\"vditor-ir__marker vditor-ir__marker--link\">".concat(Lute.EscapeHTMLStr(src), "</span>"), Lute.WalkContinue];
                    }
                    else if (vditor.currentMode === "wysiwyg") {
                        return ["", Lute.WalkContinue];
                    }
                    else {
                        return ["<span class=\"vditor-sv__marker--link\">".concat(Lute.EscapeHTMLStr(src), "</span>"), Lute.WalkContinue];
                    }
                };
                // 浏览器地址栏拷贝处理
                if (textHTML.replace(/&amp;/g, "&").replace(/<(|\/)(html|body|meta)[^>]*?>/ig, "").trim() ===
                    "<a href=\"".concat(textPlain, "\">").concat(textPlain, "</a>") ||
                    textHTML.replace(/&amp;/g, "&").replace(/<(|\/)(html|body|meta)[^>]*?>/ig, "").trim() ===
                        "<!--StartFragment--><a href=\"".concat(textPlain, "\">").concat(textPlain, "</a><!--EndFragment-->")) {
                    textHTML = "";
                }
                doc = new DOMParser().parseFromString(textHTML, "text/html");
                if (doc.body) {
                    textHTML = doc.body.innerHTML;
                }
                textHTML = Lute.Sanitize(textHTML);
                vditor.wysiwyg.getComments(vditor);
                height = vditor[vditor.currentMode].element.scrollHeight;
                code = processPasteCode(textHTML, textPlain, vditor.currentMode);
                codeElement = vditor.currentMode === "sv" ?
                    (0,hasClosest/* hasClosestByAttribute */.a1)(event.target, "data-type", "code-block") :
                    (0,hasClosest/* hasClosestByMatchTag */.lG)(event.target, "CODE");
                if (!codeElement) return [3 /*break*/, 1];
                // 粘贴在代码位置
                if (vditor.currentMode === "sv") {
                    document.execCommand("insertHTML", false, textPlain.replace(/&/g, "&amp;").replace(/</g, "&lt;"));
                }
                else {
                    position = (0,selection/* getSelectPosition */.im)(event.target, vditor[vditor.currentMode].element);
                    if (codeElement.parentElement.tagName !== "PRE") {
                        // https://github.com/Vanessa219/vditor/issues/463
                        textPlain += constants/* Constants.ZWSP */.g.ZWSP;
                    }
                    codeElement.textContent = codeElement.textContent.substring(0, position.start)
                        + textPlain + codeElement.textContent.substring(position.end);
                    (0,selection/* setSelectionByPosition */.$j)(position.start + textPlain.length, position.start + textPlain.length, codeElement.parentElement);
                    if ((_a = codeElement.parentElement) === null || _a === void 0 ? void 0 : _a.nextElementSibling.classList.contains("vditor-".concat(vditor.currentMode, "__preview"))) {
                        codeElement.parentElement.nextElementSibling.innerHTML = codeElement.outerHTML;
                        processCodeRender(codeElement.parentElement.nextElementSibling, vditor);
                    }
                }
                return [3 /*break*/, 8];
            case 1:
                if (!code) return [3 /*break*/, 2];
                callback.pasteCode(code);
                return [3 /*break*/, 8];
            case 2:
                if (!(textHTML.trim() !== "")) return [3 /*break*/, 3];
                tempElement = document.createElement("div");
                tempElement.innerHTML = textHTML;
                tempElement.querySelectorAll("[style]").forEach(function (e) {
                    e.removeAttribute("style");
                });
                tempElement.querySelectorAll(".vditor-copy").forEach(function (e) {
                    e.remove();
                });
                if (vditor.currentMode === "ir") {
                    renderers.HTML2VditorIRDOM = { renderLinkDest: renderLinkDest };
                    vditor.lute.SetJSRenderers({ renderers: renderers });
                    (0,selection/* insertHTML */.oC)(vditor.lute.HTML2VditorIRDOM(tempElement.innerHTML), vditor);
                }
                else if (vditor.currentMode === "wysiwyg") {
                    renderers.HTML2VditorDOM = { renderLinkDest: renderLinkDest };
                    vditor.lute.SetJSRenderers({ renderers: renderers });
                    (0,selection/* insertHTML */.oC)(vditor.lute.HTML2VditorDOM(tempElement.innerHTML), vditor);
                }
                else {
                    renderers.Md2VditorSVDOM = { renderLinkDest: renderLinkDest };
                    vditor.lute.SetJSRenderers({ renderers: renderers });
                    processPaste(vditor, vditor.lute.HTML2Md(tempElement.innerHTML).trimRight());
                }
                vditor.outline.render(vditor);
                return [3 /*break*/, 8];
            case 3:
                if (!(files.length > 0)) return [3 /*break*/, 7];
                if (!(vditor.options.upload.url || vditor.options.upload.handler)) return [3 /*break*/, 5];
                return [4 /*yield*/, uploadFiles(vditor, files)];
            case 4:
                _b.sent();
                return [3 /*break*/, 6];
            case 5:
                fileReader_1 = new FileReader();
                if ("clipboardData" in event) {
                    files = event.clipboardData.files;
                    file_1 = files[0];
                }
                else if (event.dataTransfer.types.includes("Files")) {
                    files = event.dataTransfer.items;
                    file_1 = files[0].getAsFile();
                }
                if (file_1 && file_1.type.startsWith("image")) {
                    fileReader_1.readAsDataURL(file_1);
                    fileReader_1.onload = function () {
                        var imgHTML = '';
                        if (vditor.currentMode === "wysiwyg") {
                            imgHTML += "<img alt=\"".concat(file_1.name, "\" src=\"").concat(fileReader_1.result.toString(), "\">\n");
                        }
                        else {
                            imgHTML += "![".concat(file_1.name, "](").concat(fileReader_1.result.toString(), ")\n");
                        }
                        document.execCommand("insertHTML", false, imgHTML);
                    };
                }
                _b.label = 6;
            case 6: return [3 /*break*/, 8];
            case 7:
                if (textPlain.trim() !== "" && files.length === 0) {
                    range = (0,selection/* getEditorRange */.zh)(vditor);
                    if (range.toString() !== "" && vditor.lute.IsValidLinkDest(textPlain)) {
                        textPlain = "[".concat(range.toString(), "](").concat(textPlain, ")");
                    }
                    if (vditor.currentMode === "ir") {
                        renderers.Md2VditorIRDOM = { renderLinkDest: renderLinkDest };
                        vditor.lute.SetJSRenderers({ renderers: renderers });
                        (0,selection/* insertHTML */.oC)(vditor.lute.Md2VditorIRDOM(textPlain), vditor);
                    }
                    else if (vditor.currentMode === "wysiwyg") {
                        renderers.Md2VditorDOM = { renderLinkDest: renderLinkDest };
                        vditor.lute.SetJSRenderers({ renderers: renderers });
                        (0,selection/* insertHTML */.oC)(vditor.lute.Md2VditorDOM(textPlain), vditor);
                    }
                    else {
                        renderers.Md2VditorSVDOM = { renderLinkDest: renderLinkDest };
                        vditor.lute.SetJSRenderers({ renderers: renderers });
                        processPaste(vditor, textPlain);
                    }
                    vditor.outline.render(vditor);
                }
                _b.label = 8;
            case 8:
                if (vditor.currentMode !== "sv") {
                    blockElement = (0,hasClosest/* hasClosestBlock */.F9)((0,selection/* getEditorRange */.zh)(vditor).startContainer);
                    if (blockElement) {
                        range = (0,selection/* getEditorRange */.zh)(vditor);
                        vditor[vditor.currentMode].element.querySelectorAll("wbr").forEach(function (wbr) {
                            wbr.remove();
                        });
                        range.insertNode(document.createElement("wbr"));
                        if (vditor.currentMode === "wysiwyg") {
                            blockElement.outerHTML = vditor.lute.SpinVditorDOM(blockElement.outerHTML);
                        }
                        else {
                            blockElement.outerHTML = vditor.lute.SpinVditorIRDOM(blockElement.outerHTML);
                        }
                        (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, range);
                    }
                    vditor[vditor.currentMode].element.querySelectorAll(".vditor-".concat(vditor.currentMode, "__preview[data-render='2']"))
                        .forEach(function (item) {
                        processCodeRender(item, vditor);
                    });
                }
                vditor.wysiwyg.triggerRemoveComment(vditor);
                execAfterRender(vditor);
                if (vditor[vditor.currentMode].element.scrollHeight - height >
                    Math.min(vditor[vditor.currentMode].element.clientHeight, window.innerHeight) / 2) {
                    scrollCenter(vditor);
                }
                return [2 /*return*/];
        }
    });
}); };
var templateObject_1;

;// CONCATENATED MODULE: ./src/ts/ir/process.ts









var processHint = function (vditor) {
    vditor.hint.render(vditor);
    var startContainer = (0,selection/* getEditorRange */.zh)(vditor).startContainer;
    // 代码块语言提示
    var preBeforeElement = (0,hasClosest/* hasClosestByAttribute */.a1)(startContainer, "data-type", "code-block-info");
    if (preBeforeElement) {
        if (preBeforeElement.textContent.replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "" && vditor.hint.recentLanguage) {
            preBeforeElement.textContent = constants/* Constants.ZWSP */.g.ZWSP + vditor.hint.recentLanguage;
            var range = (0,selection/* getEditorRange */.zh)(vditor);
            range.selectNodeContents(preBeforeElement);
        }
        else {
            var matchLangData_1 = [];
            var key_1 = preBeforeElement.textContent.substring(0, (0,selection/* getSelectPosition */.im)(preBeforeElement, vditor.ir.element).start)
                .replace(constants/* Constants.ZWSP */.g.ZWSP, "");
            (vditor.options.preview.hljs.langs || constants/* Constants.CODE_LANGUAGES */.g.CODE_LANGUAGES).forEach(function (keyName) {
                if (keyName.indexOf(key_1.toLowerCase()) > -1) {
                    matchLangData_1.push({
                        html: keyName,
                        value: keyName,
                    });
                }
            });
            vditor.hint.genHTML(matchLangData_1, key_1, vditor);
        }
    }
};
var process_processAfterRender = function (vditor, options) {
    if (options === void 0) { options = {
        enableAddUndoStack: true,
        enableHint: false,
        enableInput: true,
    }; }
    if (options.enableHint) {
        processHint(vditor);
    }
    clearTimeout(vditor.ir.processTimeoutId);
    vditor.ir.processTimeoutId = window.setTimeout(function () {
        if (vditor.ir.composingLock) {
            return;
        }
        var text = getMarkdown(vditor);
        if (typeof vditor.options.input === "function" && options.enableInput) {
            vditor.options.input(text);
        }
        if (vditor.options.counter.enable) {
            vditor.counter.render(vditor, text);
        }
        if (vditor.options.cache.enable && (0,compatibility/* accessLocalStorage */.pK)()) {
            localStorage.setItem(vditor.options.cache.id, text);
            if (vditor.options.cache.after) {
                vditor.options.cache.after(text);
            }
        }
        if (vditor.devtools) {
            vditor.devtools.renderEchart(vditor);
        }
        if (options.enableAddUndoStack) {
            vditor.undo.addToUndoStack(vditor);
        }
    }, vditor.options.undoDelay);
};
var process_processHeading = function (vditor, value) {
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var headingElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer) || range.startContainer;
    if (headingElement) {
        var headingMarkerElement = headingElement.querySelector(".vditor-ir__marker--heading");
        if (headingMarkerElement) {
            headingMarkerElement.innerHTML = value;
        }
        else {
            headingElement.insertAdjacentText("afterbegin", value);
            range.selectNodeContents(headingElement);
            range.collapse(false);
        }
        input(vditor, range.cloneRange());
        highlightToolbarIR(vditor);
    }
};
var removeInline = function (range, vditor, type) {
    var inlineElement = (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-type", type);
    if (inlineElement) {
        inlineElement.firstElementChild.remove();
        inlineElement.lastElementChild.remove();
        range.insertNode(document.createElement("wbr"));
        var tempElement = document.createElement("div");
        tempElement.innerHTML = vditor.lute.SpinVditorIRDOM(inlineElement.outerHTML);
        inlineElement.outerHTML = tempElement.firstElementChild.innerHTML.trim();
    }
};
var process_processToolbar = function (vditor, actionBtn, prefix, suffix) {
    var range = (0,selection/* getEditorRange */.zh)(vditor);
    var commandName = actionBtn.getAttribute("data-type");
    var typeElement = range.startContainer;
    if (typeElement.nodeType === 3) {
        typeElement = typeElement.parentElement;
    }
    var useHighlight = true;
    // 移除
    if (actionBtn.classList.contains("vditor-menu--current")) {
        if (commandName === "quote") {
            var quoteElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(typeElement, "BLOCKQUOTE");
            if (quoteElement) {
                range.insertNode(document.createElement("wbr"));
                quoteElement.outerHTML = quoteElement.innerHTML.trim() === "" ?
                    "<p data-block=\"0\">".concat(quoteElement.innerHTML, "</p>") : quoteElement.innerHTML;
            }
        }
        else if (commandName === "link") {
            var aElement = (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-type", "a");
            if (aElement) {
                var aTextElement = (0,hasClosest/* hasClosestByClassName */.fb)(range.startContainer, "vditor-ir__link");
                if (aTextElement) {
                    range.insertNode(document.createElement("wbr"));
                    aElement.outerHTML = aTextElement.innerHTML;
                }
                else {
                    aElement.outerHTML = aElement.querySelector(".vditor-ir__link").innerHTML + "<wbr>";
                }
            }
        }
        else if (commandName === "italic") {
            removeInline(range, vditor, "em");
        }
        else if (commandName === "bold") {
            removeInline(range, vditor, "strong");
        }
        else if (commandName === "strike") {
            removeInline(range, vditor, "s");
        }
        else if (commandName === "inline-code") {
            removeInline(range, vditor, "code");
        }
        else if (commandName === "check" || commandName === "list" || commandName === "ordered-list") {
            listToggle(vditor, range, commandName);
            useHighlight = false;
            actionBtn.classList.remove("vditor-menu--current");
        }
    }
    else {
        // 添加
        if (vditor.ir.element.childNodes.length === 0) {
            vditor.ir.element.innerHTML = '<p data-block="0"><wbr></p>';
            (0,selection/* setRangeByWbr */.ib)(vditor.ir.element, range);
        }
        var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
        if (commandName === "line") {
            if (blockElement) {
                var hrHTML = '<hr data-block="0"><p data-block="0"><wbr>\n</p>';
                if (blockElement.innerHTML.trim() === "") {
                    blockElement.outerHTML = hrHTML;
                }
                else {
                    blockElement.insertAdjacentHTML("afterend", hrHTML);
                }
            }
        }
        else if (commandName === "quote") {
            if (blockElement) {
                range.insertNode(document.createElement("wbr"));
                blockElement.outerHTML = "<blockquote data-block=\"0\">".concat(blockElement.outerHTML, "</blockquote>");
                useHighlight = false;
                actionBtn.classList.add("vditor-menu--current");
            }
        }
        else if (commandName === "link") {
            var html = void 0;
            if (range.toString() === "") {
                html = "".concat(prefix, "<wbr>").concat(suffix);
            }
            else {
                html = "".concat(prefix).concat(range.toString()).concat(suffix.replace(")", "<wbr>)"));
            }
            document.execCommand("insertHTML", false, html);
            useHighlight = false;
            actionBtn.classList.add("vditor-menu--current");
        }
        else if (commandName === "italic" || commandName === "bold" || commandName === "strike"
            || commandName === "inline-code" || commandName === "code" || commandName === "table") {
            var html = void 0;
            if (range.toString() === "") {
                html = "".concat(prefix, "<wbr>").concat(suffix);
            }
            else {
                if (commandName === "code") {
                    html = "".concat(prefix, "\n").concat(range.toString(), "<wbr>").concat(suffix);
                }
                else if (commandName === "table") {
                    html = "".concat(prefix).concat(range.toString(), "<wbr>").concat(suffix);
                }
                else {
                    html = "".concat(prefix).concat(range.toString()).concat(suffix, "<wbr>");
                }
                range.deleteContents();
            }
            if (commandName === "table" || commandName === "code") {
                html = "\n" + html + "\n\n";
            }
            var spanElement = document.createElement("span");
            spanElement.innerHTML = html;
            range.insertNode(spanElement);
            input(vditor, range);
            if (commandName === "table") {
                range.selectNodeContents(getSelection().getRangeAt(0).startContainer.parentElement);
                (0,selection/* setSelectionFocus */.Hc)(range);
            }
        }
        else if (commandName === "check" || commandName === "list" || commandName === "ordered-list") {
            listToggle(vditor, range, commandName, false);
            useHighlight = false;
            removeCurrentToolbar(vditor.toolbar.elements, ["check", "list", "ordered-list"]);
            actionBtn.classList.add("vditor-menu--current");
        }
    }
    (0,selection/* setRangeByWbr */.ib)(vditor.ir.element, range);
    process_processAfterRender(vditor);
    if (useHighlight) {
        highlightToolbarIR(vditor);
    }
};

;// CONCATENATED MODULE: ./src/ts/hint/index.ts
var hint_awaiter = (undefined && undefined.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var hint_generator = (undefined && undefined.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g;
    return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};








var Hint = /** @class */ (function () {
    function Hint(hintExtends) {
        var _this = this;
        this.splitChar = "";
        this.lastIndex = -1;
        this.fillEmoji = function (element, vditor) {
            _this.element.style.display = "none";
            var value = decodeURIComponent(element.getAttribute("data-value"));
            var range = window.getSelection().getRangeAt(0);
            // 代码提示
            if (vditor.currentMode === "ir") {
                var preBeforeElement = (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-type", "code-block-info");
                if (preBeforeElement) {
                    preBeforeElement.textContent = constants/* Constants.ZWSP */.g.ZWSP + value.trimRight();
                    range.selectNodeContents(preBeforeElement);
                    range.collapse(false);
                    process_processAfterRender(vditor);
                    preBeforeElement.parentElement.querySelectorAll("code").forEach(function (item) {
                        item.className = "language-" + value.trimRight();
                    });
                    processCodeRender(preBeforeElement.parentElement.querySelector(".vditor-ir__preview"), vditor);
                    _this.recentLanguage = value.trimRight();
                    return;
                }
            }
            if (vditor.currentMode === "wysiwyg" && range.startContainer.nodeType !== 3) {
                var startContainer = range.startContainer;
                var inputElement = void 0;
                if (startContainer.classList.contains("vditor-input")) {
                    inputElement = startContainer;
                }
                else {
                    inputElement = startContainer.firstElementChild;
                }
                if (inputElement && inputElement.classList.contains("vditor-input")) {
                    inputElement.value = value.trimRight();
                    range.selectNodeContents(inputElement);
                    range.collapse(false);
                    // {detail: 1}用于标识这个自定义事件是在编程语言选择后触发的
                    // 用于在鼠标选择语言后，自动聚焦到代码输入框
                    inputElement.dispatchEvent(new CustomEvent("input", { detail: 1 }));
                    _this.recentLanguage = value.trimRight();
                    return;
                }
            }
            range.setStart(range.startContainer, _this.lastIndex);
            range.deleteContents();
            if (vditor.options.hint.parse) {
                if (vditor.currentMode === "sv") {
                    (0,selection/* insertHTML */.oC)(vditor.lute.SpinVditorSVDOM(value), vditor);
                }
                else if (vditor.currentMode === "wysiwyg") {
                    (0,selection/* insertHTML */.oC)(vditor.lute.SpinVditorDOM(value), vditor);
                }
                else {
                    (0,selection/* insertHTML */.oC)(vditor.lute.SpinVditorIRDOM(value), vditor);
                }
            }
            else {
                (0,selection/* insertHTML */.oC)(value, vditor);
            }
            if (_this.splitChar === ":" && value.indexOf(":") > -1 && vditor.currentMode !== "sv") {
                range.insertNode(document.createTextNode(" "));
            }
            range.collapse(false);
            (0,selection/* setSelectionFocus */.Hc)(range);
            if (vditor.currentMode === "wysiwyg") {
                var preElement = (0,hasClosest/* hasClosestByClassName */.fb)(range.startContainer, "vditor-wysiwyg__block");
                if (preElement && preElement.lastElementChild.classList.contains("vditor-wysiwyg__preview")) {
                    preElement.lastElementChild.innerHTML = preElement.firstElementChild.innerHTML;
                    processCodeRender(preElement.lastElementChild, vditor);
                }
            }
            else if (vditor.currentMode === "ir") {
                var preElement = (0,hasClosest/* hasClosestByClassName */.fb)(range.startContainer, "vditor-ir__marker--pre");
                if (preElement && preElement.nextElementSibling.classList.contains("vditor-ir__preview")) {
                    preElement.nextElementSibling.innerHTML = preElement.innerHTML;
                    processCodeRender(preElement.nextElementSibling, vditor);
                }
            }
            execAfterRender(vditor);
        };
        this.timeId = -1;
        this.element = document.createElement("div");
        this.element.className = "vditor-hint";
        this.recentLanguage = "";
        hintExtends.push({ key: ":" });
    }
    Hint.prototype.render = function (vditor) {
        var _this = this;
        if (!window.getSelection().focusNode) {
            return;
        }
        var currentLineValue;
        var range = getSelection().getRangeAt(0);
        currentLineValue = range.startContainer.textContent.substring(0, range.startOffset) || "";
        var key = this.getKey(currentLineValue, vditor.options.hint.extend);
        if (typeof key === "undefined") {
            this.element.style.display = "none";
            clearTimeout(this.timeId);
        }
        else {
            if (this.splitChar === ":") {
                var emojiHint_1 = key === "" ? vditor.options.hint.emoji : vditor.lute.GetEmojis();
                var matchEmojiData_1 = [];
                Object.keys(emojiHint_1).forEach(function (keyName) {
                    if (keyName.indexOf(key.toLowerCase()) === 0) {
                        if (emojiHint_1[keyName].indexOf(".") > -1) {
                            matchEmojiData_1.push({
                                html: "<img src=\"".concat(emojiHint_1[keyName], "\" title=\":").concat(keyName, ":\"/> :").concat(keyName, ":"),
                                value: ":".concat(keyName, ":"),
                            });
                        }
                        else {
                            matchEmojiData_1.push({
                                html: "<span class=\"vditor-hint__emoji\">".concat(emojiHint_1[keyName], "</span>").concat(keyName),
                                value: emojiHint_1[keyName],
                            });
                        }
                    }
                });
                this.genHTML(matchEmojiData_1, key, vditor);
            }
            else {
                vditor.options.hint.extend.forEach(function (item) {
                    if (item.key === _this.splitChar) {
                        clearTimeout(_this.timeId);
                        _this.timeId = window.setTimeout(function () { return hint_awaiter(_this, void 0, void 0, function () {
                            var _a;
                            return hint_generator(this, function (_b) {
                                switch (_b.label) {
                                    case 0:
                                        _a = this.genHTML;
                                        return [4 /*yield*/, item.hint(key)];
                                    case 1:
                                        _a.apply(this, [_b.sent(), key, vditor]);
                                        return [2 /*return*/];
                                }
                            });
                        }); }, vditor.options.hint.delay);
                    }
                });
            }
        }
    };
    Hint.prototype.genHTML = function (data, key, vditor) {
        var _this = this;
        if (data.length === 0) {
            this.element.style.display = "none";
            return;
        }
        var editorElement = vditor[vditor.currentMode].element;
        var textareaPosition = (0,selection/* getCursorPosition */.Ny)(editorElement);
        var x = textareaPosition.left +
            (vditor.options.outline.position === "left" ? vditor.outline.element.offsetWidth : 0);
        var y = textareaPosition.top;
        var hintsHTML = "";
        data.forEach(function (hintData, i) {
            if (i > 7) {
                return;
            }
            // process high light
            var html = hintData.html;
            if (key !== "") {
                var lastIndex = html.lastIndexOf(">") + 1;
                var replaceHtml = html.substr(lastIndex);
                var replaceIndex = replaceHtml.toLowerCase().indexOf(key.toLowerCase());
                if (replaceIndex > -1) {
                    replaceHtml = replaceHtml.substring(0, replaceIndex) + "<b>" +
                        replaceHtml.substring(replaceIndex, replaceIndex + key.length) + "</b>" +
                        replaceHtml.substring(replaceIndex + key.length);
                    html = html.substr(0, lastIndex) + replaceHtml;
                }
            }
            hintsHTML += "<button type=\"button\" data-value=\"".concat(encodeURIComponent(hintData.value), " \"\n").concat(i === 0 ? "class='vditor-hint--current'" : "", "> ").concat(html, "</button>");
        });
        this.element.innerHTML = hintsHTML;
        var lineHeight = parseInt(document.defaultView.getComputedStyle(editorElement, null)
            .getPropertyValue("line-height"), 10);
        this.element.style.top = "".concat(y + (lineHeight || 22), "px");
        this.element.style.left = "".concat(x, "px");
        this.element.style.display = "block";
        this.element.style.right = "auto";
        this.element.querySelectorAll("button").forEach(function (element) {
            element.addEventListener("click", function (event) {
                _this.fillEmoji(element, vditor);
                event.preventDefault();
            });
        });
        // hint 展现在上部
        if (this.element.getBoundingClientRect().bottom > window.innerHeight) {
            this.element.style.top = "".concat(y - this.element.offsetHeight, "px");
        }
        if (this.element.getBoundingClientRect().right > window.innerWidth) {
            this.element.style.left = "auto";
            this.element.style.right = "0";
        }
    };
    Hint.prototype.select = function (event, vditor) {
        if (this.element.querySelectorAll("button").length === 0 ||
            this.element.style.display === "none") {
            return false;
        }
        var currentHintElement = this.element.querySelector(".vditor-hint--current");
        if (event.key === "ArrowDown") {
            event.preventDefault();
            event.stopPropagation();
            currentHintElement.removeAttribute("class");
            if (!currentHintElement.nextElementSibling) {
                this.element.children[0].className = "vditor-hint--current";
            }
            else {
                currentHintElement.nextElementSibling.className = "vditor-hint--current";
            }
            return true;
        }
        else if (event.key === "ArrowUp") {
            event.preventDefault();
            event.stopPropagation();
            currentHintElement.removeAttribute("class");
            if (!currentHintElement.previousElementSibling) {
                var length_1 = this.element.children.length;
                this.element.children[length_1 - 1].className = "vditor-hint--current";
            }
            else {
                currentHintElement.previousElementSibling.className = "vditor-hint--current";
            }
            return true;
        }
        else if (!(0,compatibility/* isCtrl */.yl)(event) && !event.shiftKey && !event.altKey && event.key === "Enter" && !event.isComposing) {
            event.preventDefault();
            event.stopPropagation();
            this.fillEmoji(currentHintElement, vditor);
            return true;
        }
        return false;
    };
    Hint.prototype.getKey = function (currentLineValue, extend) {
        var _this = this;
        this.lastIndex = -1;
        this.splitChar = "";
        extend.forEach(function (item) {
            var currentLastIndex = currentLineValue.lastIndexOf(item.key);
            if (_this.lastIndex < currentLastIndex) {
                _this.splitChar = item.key;
                _this.lastIndex = currentLastIndex;
            }
        });
        var key;
        if (this.lastIndex === -1) {
            return key;
        }
        var lineArray = currentLineValue.split(this.splitChar);
        var lastItem = lineArray[lineArray.length - 1];
        var maxLength = 32;
        if (lineArray.length > 1 && lastItem.trim() === lastItem) {
            if (lineArray.length === 2 && lineArray[0] === "" && lineArray[1].length < maxLength) {
                key = lineArray[1];
            }
            else {
                var preChar = lineArray[lineArray.length - 2].slice(-1);
                if ((0,code160to32/* code160to32 */.X)(preChar) === " " && lastItem.length < maxLength) {
                    key = lastItem;
                }
            }
        }
        return key;
    };
    return Hint;
}());


;// CONCATENATED MODULE: ./src/ts/ir/index.ts












var IR = /** @class */ (function () {
    function IR(vditor) {
        this.composingLock = false;
        var divElement = document.createElement("div");
        divElement.className = "vditor-ir";
        divElement.innerHTML = "<pre class=\"vditor-reset\" placeholder=\"".concat(vditor.options.placeholder, "\"\n contenteditable=\"true\" spellcheck=\"false\"></pre>");
        this.element = divElement.firstElementChild;
        this.bindEvent(vditor);
        focusEvent(vditor, this.element);
        dblclickEvent(vditor, this.element);
        blurEvent(vditor, this.element);
        hotkeyEvent(vditor, this.element);
        selectEvent(vditor, this.element);
        dropEvent(vditor, this.element);
        copyEvent(vditor, this.element, this.copy);
        cutEvent(vditor, this.element, this.copy);
    }
    IR.prototype.copy = function (event, vditor) {
        var range = getSelection().getRangeAt(0);
        if (range.toString() === "") {
            return;
        }
        event.stopPropagation();
        event.preventDefault();
        var tempElement = document.createElement("div");
        tempElement.appendChild(range.cloneContents());
        event.clipboardData.setData("text/plain", vditor.lute.VditorIRDOM2Md(tempElement.innerHTML).trim());
        event.clipboardData.setData("text/html", "");
    };
    IR.prototype.bindEvent = function (vditor) {
        var _this = this;
        this.element.addEventListener("paste", function (event) {
            paste(vditor, event, {
                pasteCode: function (code) {
                    document.execCommand("insertHTML", false, code);
                },
            });
        });
        this.element.addEventListener("scroll", function () {
            hidePanel(vditor, ["hint"]);
        });
        this.element.addEventListener("compositionstart", function (event) {
            _this.composingLock = true;
        });
        this.element.addEventListener("compositionend", function (event) {
            if (!(0,compatibility/* isFirefox */.vU)()) {
                input(vditor, getSelection().getRangeAt(0).cloneRange());
            }
            _this.composingLock = false;
        });
        this.element.addEventListener("input", function (event) {
            if (event.inputType === "deleteByDrag" || event.inputType === "insertFromDrop") {
                // https://github.com/Vanessa219/vditor/issues/801 编辑器内容拖拽问题
                return;
            }
            if (_this.preventInput) {
                _this.preventInput = false;
                process_processAfterRender(vditor, {
                    enableAddUndoStack: true,
                    enableHint: true,
                    enableInput: true,
                });
                return;
            }
            if (_this.composingLock || event.data === "‘" || event.data === "“" || event.data === "《") {
                return;
            }
            input(vditor, getSelection().getRangeAt(0).cloneRange(), false, event);
        });
        this.element.addEventListener("click", function (event) {
            if (event.target.tagName === "INPUT") {
                if (event.target.checked) {
                    event.target.setAttribute("checked", "checked");
                }
                else {
                    event.target.removeAttribute("checked");
                }
                _this.preventInput = true;
                process_processAfterRender(vditor);
                return;
            }
            var range = (0,selection/* getEditorRange */.zh)(vditor);
            // 点击后光标落于预览区
            var previewElement = (0,hasClosest/* hasClosestByClassName */.fb)(event.target, "vditor-ir__preview");
            if (!previewElement) {
                previewElement = (0,hasClosest/* hasClosestByClassName */.fb)(range.startContainer, "vditor-ir__preview");
            }
            if (previewElement) {
                if (previewElement.previousElementSibling.firstElementChild) {
                    range.selectNodeContents(previewElement.previousElementSibling.firstElementChild);
                }
                else {
                    // 行内数学公式
                    range.selectNodeContents(previewElement.previousElementSibling);
                }
                range.collapse(true);
                (0,selection/* setSelectionFocus */.Hc)(range);
                scrollCenter(vditor);
            }
            // 点击图片光标选中图片地址
            if (event.target.tagName === "IMG") {
                var linkElement = event.target.parentElement.querySelector(".vditor-ir__marker--link");
                if (linkElement) {
                    range.selectNode(linkElement);
                    (0,selection/* setSelectionFocus */.Hc)(range);
                }
            }
            // 打开链接
            var aElement = (0,hasClosest/* hasClosestByAttribute */.a1)(event.target, "data-type", "a");
            if (aElement && (!aElement.classList.contains("vditor-ir__node--expand"))) {
                if (vditor.options.link.click) {
                    vditor.options.link.click(aElement.querySelector(":scope > .vditor-ir__marker--link"));
                }
                else if (vditor.options.link.isOpen) {
                    window.open(aElement.querySelector(":scope > .vditor-ir__marker--link").textContent);
                }
                return;
            }
            if (event.target.isEqualNode(_this.element) && _this.element.lastElementChild && range.collapsed) {
                var lastRect = _this.element.lastElementChild.getBoundingClientRect();
                if (event.y > lastRect.top + lastRect.height) {
                    if (_this.element.lastElementChild.tagName === "P" &&
                        _this.element.lastElementChild.textContent.trim().replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "") {
                        range.selectNodeContents(_this.element.lastElementChild);
                        range.collapse(false);
                    }
                    else {
                        _this.element.insertAdjacentHTML("beforeend", "<p data-block=\"0\">".concat(constants/* Constants.ZWSP */.g.ZWSP, "<wbr></p>"));
                        (0,selection/* setRangeByWbr */.ib)(_this.element, range);
                    }
                }
            }
            if (range.toString() === "") {
                expandMarker(range, vditor);
            }
            else {
                // https://github.com/Vanessa219/vditor/pull/681 当点击选中区域时 eventTarget 与 range 不一致，需延迟等待 range 发生变化
                setTimeout(function () {
                    expandMarker((0,selection/* getEditorRange */.zh)(vditor), vditor);
                });
            }
            clickToc(event, vditor);
            highlightToolbarIR(vditor);
        });
        this.element.addEventListener("keyup", function (event) {
            if (event.isComposing || (0,compatibility/* isCtrl */.yl)(event)) {
                return;
            }
            if (event.key === "Enter") {
                scrollCenter(vditor);
            }
            highlightToolbarIR(vditor);
            if ((event.key === "Backspace" || event.key === "Delete") &&
                vditor.ir.element.innerHTML !== "" && vditor.ir.element.childNodes.length === 1 &&
                vditor.ir.element.firstElementChild && vditor.ir.element.firstElementChild.tagName === "P"
                && vditor.ir.element.firstElementChild.childElementCount === 0
                && (vditor.ir.element.textContent === "" || vditor.ir.element.textContent === "\n")) {
                // 为空时显示 placeholder
                vditor.ir.element.innerHTML = "";
                return;
            }
            var range = (0,selection/* getEditorRange */.zh)(vditor);
            if (event.key === "Backspace") {
                // firefox headings https://github.com/Vanessa219/vditor/issues/211
                if ((0,compatibility/* isFirefox */.vU)() && range.startContainer.textContent === "\n" && range.startOffset === 1) {
                    range.startContainer.textContent = "";
                    expandMarker(range, vditor);
                }
                // 数学公式前是空块，空块前是 table，在空块前删除，数学公式会多一个 br
                _this.element.querySelectorAll(".language-math").forEach(function (item) {
                    var brElement = item.querySelector("br");
                    if (brElement) {
                        brElement.remove();
                    }
                });
            }
            else if (event.key.indexOf("Arrow") > -1) {
                if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                    processHint(vditor);
                }
                expandMarker(range, vditor);
            }
            else if (event.keyCode === 229 && event.code === "" && event.key === "Unidentified") {
                // https://github.com/Vanessa219/vditor/issues/508 IR 删除到节点需展开
                expandMarker(range, vditor);
            }
            var previewRenderElement = (0,hasClosest/* hasClosestByClassName */.fb)(range.startContainer, "vditor-ir__preview");
            if (previewRenderElement) {
                if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
                    if (previewRenderElement.previousElementSibling.firstElementChild) {
                        range.selectNodeContents(previewRenderElement.previousElementSibling.firstElementChild);
                    }
                    else {
                        // 行内数学公式/html entity
                        range.selectNodeContents(previewRenderElement.previousElementSibling);
                    }
                    range.collapse(false);
                    event.preventDefault();
                    return true;
                }
                if (previewRenderElement.tagName === "SPAN" &&
                    (event.key === "ArrowDown" || event.key === "ArrowRight")) {
                    if (previewRenderElement.parentElement.getAttribute("data-type") === "html-entity") {
                        // html entity
                        previewRenderElement.parentElement.insertAdjacentText("afterend", constants/* Constants.ZWSP */.g.ZWSP);
                        range.setStart(previewRenderElement.parentElement.nextSibling, 1);
                    }
                    else {
                        range.selectNodeContents(previewRenderElement.parentElement.lastElementChild);
                    }
                    range.collapse(false);
                    event.preventDefault();
                    return true;
                }
            }
        });
    };
    return IR;
}());


;// CONCATENATED MODULE: ./src/ts/markdown/getHTML.ts

var getHTML = function (vditor) {
    if (vditor.currentMode === "sv") {
        return vditor.lute.Md2HTML(getMarkdown(vditor));
    }
    else if (vditor.currentMode === "wysiwyg") {
        return vditor.lute.VditorDOM2HTML(vditor.wysiwyg.element.innerHTML);
    }
    else if (vditor.currentMode === "ir") {
        return vditor.lute.VditorIRDOM2HTML(vditor.ir.element.innerHTML);
    }
};

// EXTERNAL MODULE: ./src/ts/markdown/setLute.ts
var setLute = __webpack_require__(65);
// EXTERNAL MODULE: ./src/ts/markdown/outlineRender.ts
var outlineRender = __webpack_require__(182);
;// CONCATENATED MODULE: ./src/ts/outline/index.ts




var Outline = /** @class */ (function () {
    function Outline(outlineLabel) {
        this.element = document.createElement("div");
        this.element.className = "vditor-outline";
        this.element.innerHTML = "<div class=\"vditor-outline__title\">".concat(outlineLabel, "</div>\n<div class=\"vditor-outline__content\"></div>");
    }
    Outline.prototype.render = function (vditor) {
        var html = "";
        if (vditor.preview.element.style.display === "block") {
            html = (0,outlineRender/* outlineRender */.k)(vditor.preview.previewElement, this.element.lastElementChild, vditor);
        }
        else {
            html = (0,outlineRender/* outlineRender */.k)(vditor[vditor.currentMode].element, this.element.lastElementChild, vditor);
        }
        return html;
    };
    Outline.prototype.toggle = function (vditor, show, focus) {
        var _a;
        if (show === void 0) { show = true; }
        if (focus === void 0) { focus = true; }
        var btnElement = (_a = vditor.toolbar.elements.outline) === null || _a === void 0 ? void 0 : _a.firstElementChild;
        if (show && window.innerWidth >= constants/* Constants.MOBILE_WIDTH */.g.MOBILE_WIDTH) {
            this.element.style.display = "block";
            this.render(vditor);
            btnElement === null || btnElement === void 0 ? void 0 : btnElement.classList.add("vditor-menu--current");
        }
        else {
            this.element.style.display = "none";
            btnElement === null || btnElement === void 0 ? void 0 : btnElement.classList.remove("vditor-menu--current");
        }
        if (focus && getSelection().rangeCount > 0) {
            var range = getSelection().getRangeAt(0);
            if (vditor[vditor.currentMode].element.contains(range.startContainer)) {
                (0,selection/* setSelectionFocus */.Hc)(range);
            }
        }
        setPadding(vditor);
    };
    return Outline;
}());


// EXTERNAL MODULE: ./src/ts/markdown/mediaRender.ts
var mediaRender = __webpack_require__(431);
;// CONCATENATED MODULE: ./src/ts/preview/index.ts


















var Preview = /** @class */ (function () {
    function Preview(vditor) {
        var _this = this;
        this.element = document.createElement("div");
        this.element.className = "vditor-preview";
        this.previewElement = document.createElement("div");
        this.previewElement.className = "vditor-reset";
        if (vditor.options.classes.preview) {
            this.previewElement.classList.add(vditor.options.classes.preview);
        }
        this.previewElement.style.maxWidth = vditor.options.preview.maxWidth + "px";
        this.previewElement.addEventListener("copy", function (event) {
            if (event.target.tagName === "TEXTAREA") {
                // https://github.com/Vanessa219/vditor/issues/901
                return;
            }
            var tempElement = document.createElement("div");
            tempElement.className = "vditor-reset";
            tempElement.appendChild(getSelection().getRangeAt(0).cloneContents());
            _this.copyToX(vditor, tempElement, "default");
            event.preventDefault();
        });
        this.previewElement.addEventListener("click", function (event) {
            var spanElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(event.target, "SPAN");
            if (spanElement && (0,hasClosest/* hasClosestByClassName */.fb)(spanElement, "vditor-toc")) {
                var headingElement = _this.previewElement.querySelector("#" + spanElement.getAttribute("data-target-id"));
                if (headingElement) {
                    _this.element.scrollTop = headingElement.offsetTop;
                }
                return;
            }
            if (event.target.tagName === "A") {
                if (vditor.options.link.click) {
                    vditor.options.link.click(event.target);
                }
                else if (vditor.options.link.isOpen) {
                    window.open(event.target.getAttribute("href"));
                }
                event.preventDefault();
                return;
            }
            if (event.target.tagName === "IMG") {
                if (vditor.options.image.preview) {
                    vditor.options.image.preview(event.target);
                }
                else if (vditor.options.image.isPreview) {
                    (0,preview_image/* previewImage */.E)(event.target, vditor.options.lang, vditor.options.theme);
                }
            }
        });
        this.element.appendChild(this.previewElement);
        var actions = vditor.options.preview.actions;
        if (actions.length === 0) {
            return;
        }
        var actionElement = document.createElement("div");
        actionElement.className = "vditor-preview__action";
        var actionHtml = [];
        for (var i = 0; i < actions.length; i++) {
            var action = actions[i];
            if (typeof action === "object") {
                actionHtml.push("<button type=\"button\" data-type=\"".concat(action.key, "\" class=\"").concat(action.className, "\"").concat(action.tooltip ? " aria-label=\"".concat(action.tooltip, "\"") : "", "\">").concat(action.text, "</button>"));
                continue;
            }
            switch (action) {
                case "desktop":
                    actionHtml.push("<button type=\"button\" class=\"vditor-preview__action--current\" data-type=\"desktop\">Desktop</button>");
                    break;
                case "tablet":
                    actionHtml.push("<button type=\"button\" data-type=\"tablet\">Tablet</button>");
                    break;
                case "mobile":
                    actionHtml.push("<button type=\"button\" data-type=\"mobile\">Mobile/Wechat</button>");
                    break;
                case "mp-wechat":
                    actionHtml.push("<button type=\"button\" data-type=\"mp-wechat\" class=\"vditor-tooltipped vditor-tooltipped__w\" aria-label=\"\u590D\u5236\u5230\u516C\u4F17\u53F7\"><svg><use xlink:href=\"#vditor-icon-mp-wechat\"></use></svg></button>");
                    break;
                case "zhihu":
                    actionHtml.push("<button type=\"button\" data-type=\"zhihu\" class=\"vditor-tooltipped vditor-tooltipped__w\" aria-label=\"\u590D\u5236\u5230\u77E5\u4E4E\"><svg><use xlink:href=\"#vditor-icon-zhihu\"></use></svg></button>");
                    break;
            }
        }
        actionElement.innerHTML = actionHtml.join("");
        actionElement.addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            var btn = (0,hasClosestByHeadings/* hasClosestByTag */.S)(event.target, "BUTTON");
            if (!btn) {
                return;
            }
            var type = btn.getAttribute("data-type");
            var actionCustom = actions.find(function (w) { return (w === null || w === void 0 ? void 0 : w.key) === type; });
            if (actionCustom) {
                actionCustom.click(type);
                return;
            }
            if (type === "mp-wechat" || type === "zhihu") {
                _this.copyToX(vditor, _this.previewElement.cloneNode(true), type);
                return;
            }
            if (type === "desktop") {
                _this.previewElement.style.width = "auto";
            }
            else if (type === "tablet") {
                _this.previewElement.style.width = "780px";
            }
            else {
                _this.previewElement.style.width = "360px";
            }
            if (_this.previewElement.scrollWidth > _this.previewElement.parentElement.clientWidth) {
                _this.previewElement.style.width = "auto";
            }
            _this.render(vditor);
            actionElement.querySelectorAll("button").forEach(function (item) {
                item.classList.remove("vditor-preview__action--current");
            });
            btn.classList.add("vditor-preview__action--current");
        });
        this.element.insertBefore(actionElement, this.previewElement);
    }
    Preview.prototype.render = function (vditor, value) {
        var _this = this;
        clearTimeout(this.mdTimeoutId);
        if (this.element.style.display === "none") {
            if (this.element.getAttribute("data-type") === "renderPerformance") {
                vditor.tip.hide();
            }
            return;
        }
        if (value) {
            this.previewElement.innerHTML = value;
            return;
        }
        if (getMarkdown(vditor)
            .replace(/^[\s\uFEFF\xA0]+|[\s\uFEFF\xA0]+$/g, "") === "") {
            this.previewElement.innerHTML = "";
            return;
        }
        var renderStartTime = new Date().getTime();
        var markdownText = getMarkdown(vditor);
        this.mdTimeoutId = window.setTimeout(function () {
            if (vditor.options.preview.url) {
                var xhr_1 = new XMLHttpRequest();
                xhr_1.open("POST", vditor.options.preview.url);
                xhr_1.setRequestHeader("Content-Type", "application/json;charset=UTF-8");
                xhr_1.onreadystatechange = function () {
                    if (xhr_1.readyState === XMLHttpRequest.DONE) {
                        if (xhr_1.status === 200) {
                            var responseJSON = JSON.parse(xhr_1.responseText);
                            if (responseJSON.code !== 0) {
                                vditor.tip.show(responseJSON.msg);
                                return;
                            }
                            if (vditor.options.preview.transform) {
                                responseJSON.data = vditor.options.preview.transform(responseJSON.data);
                            }
                            _this.previewElement.innerHTML = responseJSON.data;
                            _this.afterRender(vditor, renderStartTime);
                        }
                        else {
                            var html = vditor.lute.Md2HTML(markdownText);
                            if (vditor.options.preview.transform) {
                                html = vditor.options.preview.transform(html);
                            }
                            _this.previewElement.innerHTML = html;
                            _this.afterRender(vditor, renderStartTime);
                        }
                    }
                };
                xhr_1.send(JSON.stringify({ markdownText: markdownText }));
            }
            else {
                var html = vditor.lute.Md2HTML(markdownText);
                if (vditor.options.preview.transform) {
                    html = vditor.options.preview.transform(html);
                }
                _this.previewElement.innerHTML = html;
                _this.afterRender(vditor, renderStartTime);
            }
        }, vditor.options.preview.delay);
    };
    Preview.prototype.afterRender = function (vditor, startTime) {
        if (vditor.options.preview.parse) {
            vditor.options.preview.parse(this.element);
        }
        var time = (new Date().getTime() - startTime);
        if ((new Date().getTime() - startTime) > 2600) {
            // https://github.com/b3log/vditor/issues/67
            vditor.tip.show(window.VditorI18n.performanceTip.replace("${x}", time.toString()));
            vditor.preview.element.setAttribute("data-type", "renderPerformance");
        }
        else if (vditor.preview.element.getAttribute("data-type") === "renderPerformance") {
            vditor.tip.hide();
            vditor.preview.element.removeAttribute("data-type");
        }
        var cmtFocusElement = vditor.preview.element.querySelector(".vditor-comment--focus");
        if (cmtFocusElement) {
            cmtFocusElement.classList.remove("vditor-comment--focus");
        }
        (0,codeRender/* codeRender */.O)(vditor.preview.previewElement, vditor.options.preview.hljs);
        (0,highlightRender/* highlightRender */.s)(vditor.options.preview.hljs, vditor.preview.previewElement, vditor.options.cdn);
        (0,mermaidRender/* mermaidRender */.i)(vditor.preview.previewElement, vditor.options.cdn, vditor.options.theme);
        (0,markmapRender/* markmapRender */.K)(vditor.preview.previewElement, vditor.options.cdn, vditor.options.theme);
        (0,flowchartRender/* flowchartRender */.P)(vditor.preview.previewElement, vditor.options.cdn);
        (0,graphvizRender/* graphvizRender */.v)(vditor.preview.previewElement, vditor.options.cdn);
        (0,chartRender/* chartRender */.p)(vditor.preview.previewElement, vditor.options.cdn, vditor.options.theme);
        (0,mindmapRender/* mindmapRender */.P)(vditor.preview.previewElement, vditor.options.cdn, vditor.options.theme);
        (0,plantumlRender/* plantumlRender */.B)(vditor.preview.previewElement, vditor.options.cdn);
        (0,abcRender/* abcRender */.Q)(vditor.preview.previewElement, vditor.options.cdn);
        if (vditor.options.preview.render.media.enable) {
            (0,mediaRender/* mediaRender */.Y)(vditor.preview.previewElement);
        }
        vditor.options.customRenders.forEach(function (item) {
            item.render(vditor.preview.previewElement, vditor);
        });
        // toc render
        var editorElement = vditor.preview.element;
        var tocHTML = vditor.outline.render(vditor);
        if (tocHTML === "") {
            tocHTML = "[ToC]";
        }
        editorElement.querySelectorAll('[data-type="toc-block"]').forEach(function (item) {
            item.innerHTML = tocHTML;
            (0,mathRender/* mathRender */.H)(item, {
                cdn: vditor.options.cdn,
                math: vditor.options.preview.math,
            });
        });
        (0,mathRender/* mathRender */.H)(vditor.preview.previewElement, {
            cdn: vditor.options.cdn,
            math: vditor.options.preview.math,
        });
    };
    Preview.prototype.copyToX = function (vditor, copyElement, type) {
        if (type === void 0) { type = "mp-wechat"; }
        // fix math render
        if (type !== "zhihu") {
            copyElement.querySelectorAll(".katex-html .base").forEach(function (item) {
                item.style.display = "initial";
            });
        }
        else {
            copyElement.querySelectorAll(".language-math").forEach(function (item) {
                item.outerHTML = "<img class=\"Formula-image\" data-eeimg=\"true\" src=\"//www.zhihu.com/equation?tex=\" alt=\"".concat(item.getAttribute("data-math"), "\\\" style=\"display: block; margin: 0 auto; max-width: 100%;\">");
            });
        }
        // 防止背景色被粘贴到公众号中
        copyElement.style.backgroundColor = "#fff";
        // 代码背景
        copyElement.querySelectorAll("code").forEach(function (item) {
            item.style.backgroundImage = "none";
        });
        this.element.append(copyElement);
        var range = copyElement.ownerDocument.createRange();
        range.selectNode(copyElement);
        (0,selection/* setSelectionFocus */.Hc)(range);
        document.execCommand("copy");
        copyElement.remove();
        vditor.tip.show(['zhihu', 'mp-wechat'].includes(type) ? "\u5DF2\u590D\u5236\uFF0C\u53EF\u5230".concat(type === "zhihu" ? "知乎" : "微信公众号平台", "\u8FDB\u884C\u7C98\u8D34") : "\u5DF2\u590D\u5236\u5230\u526A\u5207\u677F");
    };
    return Preview;
}());


;// CONCATENATED MODULE: ./src/ts/resize/index.ts
var Resize = /** @class */ (function () {
    function Resize(vditor) {
        this.element = document.createElement("div");
        this.element.className = "vditor-resize vditor-resize--".concat(vditor.options.resize.position);
        this.element.innerHTML = "<div><svg><use xlink:href=\"#vditor-icon-resize\"></use></svg></div>";
        this.bindEvent(vditor);
    }
    Resize.prototype.bindEvent = function (vditor) {
        var _this = this;
        this.element.addEventListener("mousedown", function (event) {
            var documentSelf = document;
            var y = event.clientY;
            var height = vditor.element.offsetHeight;
            var minHeight = 63 + vditor.element.querySelector(".vditor-toolbar").clientHeight;
            documentSelf.ondragstart = function () { return false; };
            if (window.captureEvents) {
                window.captureEvents();
            }
            _this.element.classList.add("vditor-resize--selected");
            documentSelf.onmousemove = function (moveEvent) {
                if (vditor.options.resize.position === "top") {
                    vditor.element.style.height = Math.max(minHeight, height + (y - moveEvent.clientY)) + "px";
                }
                else {
                    vditor.element.style.height = Math.max(minHeight, height + (moveEvent.clientY - y)) + "px";
                }
                if (vditor.options.typewriterMode) {
                    vditor.sv.element.style.paddingBottom =
                        vditor.sv.element.parentElement.offsetHeight / 2 + "px";
                }
            };
            documentSelf.onmouseup = function () {
                if (vditor.options.resize.after) {
                    vditor.options.resize.after(vditor.element.offsetHeight - height);
                }
                if (window.captureEvents) {
                    window.captureEvents();
                }
                documentSelf.onmousemove = null;
                documentSelf.onmouseup = null;
                documentSelf.ondragstart = null;
                documentSelf.onselectstart = null;
                documentSelf.onselect = null;
                _this.element.classList.remove("vditor-resize--selected");
            };
        });
    };
    return Resize;
}());


;// CONCATENATED MODULE: ./src/ts/sv/index.ts






var Editor = /** @class */ (function () {
    function Editor(vditor) {
        this.composingLock = false;
        this.element = document.createElement("pre");
        this.element.className = "vditor-sv vditor-reset";
        this.element.setAttribute("placeholder", vditor.options.placeholder);
        this.element.setAttribute("contenteditable", "true");
        this.element.setAttribute("spellcheck", "false");
        this.bindEvent(vditor);
        focusEvent(vditor, this.element);
        blurEvent(vditor, this.element);
        hotkeyEvent(vditor, this.element);
        selectEvent(vditor, this.element);
        dropEvent(vditor, this.element);
        copyEvent(vditor, this.element, this.copy);
        cutEvent(vditor, this.element, this.copy);
    }
    Editor.prototype.copy = function (event, vditor) {
        event.stopPropagation();
        event.preventDefault();
        event.clipboardData.setData("text/plain", getSelectText(vditor[vditor.currentMode].element));
    };
    Editor.prototype.bindEvent = function (vditor) {
        var _this = this;
        this.element.addEventListener("paste", function (event) {
            paste(vditor, event, {
                pasteCode: function (code) {
                    document.execCommand("insertHTML", false, code);
                },
            });
        });
        this.element.addEventListener("scroll", function () {
            if (vditor.preview.element.style.display !== "block") {
                return;
            }
            var textScrollTop = _this.element.scrollTop;
            var textHeight = _this.element.clientHeight;
            var textScrollHeight = _this.element.scrollHeight - parseFloat(_this.element.style.paddingBottom || "0");
            var preview = vditor.preview.element;
            if ((textScrollTop / textHeight > 0.5)) {
                preview.scrollTop = (textScrollTop + textHeight) *
                    preview.scrollHeight / textScrollHeight - textHeight;
            }
            else {
                preview.scrollTop = textScrollTop *
                    preview.scrollHeight / textScrollHeight;
            }
        });
        this.element.addEventListener("compositionstart", function (event) {
            _this.composingLock = true;
        });
        this.element.addEventListener("compositionend", function (event) {
            if (!(0,compatibility/* isFirefox */.vU)()) {
                inputEvent(vditor, event);
            }
            _this.composingLock = false;
        });
        this.element.addEventListener("input", function (event) {
            if (event.inputType === "deleteByDrag" || event.inputType === "insertFromDrop") {
                // https://github.com/Vanessa219/vditor/issues/801 编辑器内容拖拽问题
                return;
            }
            if (_this.composingLock || event.data === "‘" || event.data === "“" || event.data === "《") {
                return;
            }
            if (_this.preventInput) {
                _this.preventInput = false;
                processAfterRender(vditor, {
                    enableAddUndoStack: true,
                    enableHint: true,
                    enableInput: true,
                });
                return;
            }
            inputEvent(vditor, event);
        });
        this.element.addEventListener("keyup", function (event) {
            if (event.isComposing || (0,compatibility/* isCtrl */.yl)(event)) {
                return;
            }
            if ((event.key === "Backspace" || event.key === "Delete") &&
                vditor.sv.element.innerHTML !== "" && vditor.sv.element.childNodes.length === 1 &&
                vditor.sv.element.firstElementChild && vditor.sv.element.firstElementChild.tagName === "DIV"
                && vditor.sv.element.firstElementChild.childElementCount === 2
                && (vditor.sv.element.firstElementChild.textContent === "" || vditor.sv.element.textContent === "\n")) {
                // 为空时显示 placeholder
                vditor.sv.element.innerHTML = "";
                return;
            }
            if (event.key === "Enter") {
                scrollCenter(vditor);
            }
        });
    };
    return Editor;
}());


;// CONCATENATED MODULE: ./src/ts/tip/index.ts
var Tip = /** @class */ (function () {
    function Tip() {
        this.element = document.createElement("div");
        this.element.className = "vditor-tip";
    }
    Tip.prototype.show = function (text, time) {
        var _this = this;
        if (time === void 0) { time = 6000; }
        this.element.className = "vditor-tip vditor-tip--show";
        if (time === 0) {
            this.element.innerHTML = "<div class=\"vditor-tip__content\">".concat(text, "\n<div class=\"vditor-tip__close\">X</div></div>");
            this.element.querySelector(".vditor-tip__close").addEventListener("click", function () {
                _this.hide();
            });
        }
        else {
            this.element.innerHTML = "<div class=\"vditor-tip__content\">".concat(text, "</div>");
            setTimeout(function () {
                _this.hide();
            }, time);
        }
        // 需在动画结束后才能确定位置
        this.element.removeAttribute("style");
        setTimeout(function () {
            var rect = _this.element.getBoundingClientRect();
            if (rect.top < 46) {
                _this.element.style.position = "fixed";
                _this.element.style.top = "46px";
            }
        }, 150);
    };
    Tip.prototype.hide = function () {
        this.element.className = "vditor-messageElementtip";
        this.element.innerHTML = "";
    };
    return Tip;
}());


;// CONCATENATED MODULE: ./src/ts/ui/setPreviewMode.ts


var setPreviewMode = function (mode, vditor) {
    if (vditor.options.preview.mode === mode) {
        return;
    }
    vditor.options.preview.mode = mode;
    switch (mode) {
        case "both":
            vditor.sv.element.style.display = "block";
            vditor.preview.element.style.display = "block";
            vditor.preview.render(vditor);
            setCurrentToolbar(vditor.toolbar.elements, ["both"]);
            break;
        case "editor":
            vditor.sv.element.style.display = "block";
            vditor.preview.element.style.display = "none";
            removeCurrentToolbar(vditor.toolbar.elements, ["both"]);
            break;
        default:
            break;
    }
    if (vditor.devtools) {
        vditor.devtools.renderEchart(vditor);
    }
};

;// CONCATENATED MODULE: ./src/ts/toolbar/Both.ts
var Both_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();




var Both = /** @class */ (function (_super) {
    Both_extends(Both, _super);
    function Both(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        if (vditor.options.preview.mode === "both") {
            _this.element.children[0].classList.add("vditor-menu--current");
        }
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            var btnElement = _this.element.firstElementChild;
            if (btnElement.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            event.preventDefault();
            if (vditor.currentMode !== "sv") {
                return;
            }
            if (vditor.options.preview.mode === "both") {
                setPreviewMode("editor", vditor);
            }
            else {
                setPreviewMode("both", vditor);
            }
        });
        return _this;
    }
    return Both;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Br.ts
var Br = /** @class */ (function () {
    function Br() {
        this.element = document.createElement("div");
        this.element.className = "vditor-toolbar__br";
    }
    return Br;
}());


// EXTERNAL MODULE: ./src/ts/ui/setCodeTheme.ts
var setCodeTheme = __webpack_require__(34);
;// CONCATENATED MODULE: ./src/ts/toolbar/CodeTheme.ts
var CodeTheme_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();





var CodeTheme = /** @class */ (function (_super) {
    CodeTheme_extends(CodeTheme, _super);
    function CodeTheme(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        var actionBtn = _this.element.children[0];
        var panelElement = document.createElement("div");
        panelElement.className = "vditor-hint".concat(menuItem.level === 2 ? "" : " vditor-panel--arrow");
        var innerHTML = "";
        constants/* Constants.CODE_THEME.forEach */.g.CODE_THEME.forEach(function (theme) {
            innerHTML += "<button>".concat(theme, "</button>");
        });
        panelElement.innerHTML =
            "<div style=\"overflow: auto;max-height:".concat(window.innerHeight / 2, "px\">").concat(innerHTML, "</div>");
        panelElement.addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            if (event.target.tagName === "BUTTON") {
                hidePanel(vditor, ["subToolbar"]);
                vditor.options.preview.hljs.style = event.target.textContent;
                (0,setCodeTheme/* setCodeTheme */.Y)(event.target.textContent, vditor.options.cdn);
                event.preventDefault();
                event.stopPropagation();
            }
        });
        _this.element.appendChild(panelElement);
        toggleSubMenu(vditor, panelElement, actionBtn, menuItem.level);
        return _this;
    }
    return CodeTheme;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/ContentTheme.ts
var ContentTheme_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();




var ContentTheme = /** @class */ (function (_super) {
    ContentTheme_extends(ContentTheme, _super);
    function ContentTheme(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        var actionBtn = _this.element.children[0];
        var panelElement = document.createElement("div");
        panelElement.className = "vditor-hint".concat(menuItem.level === 2 ? "" : " vditor-panel--arrow");
        var innerHTML = "";
        Object.keys(vditor.options.preview.theme.list).forEach(function (key) {
            innerHTML += "<button data-type=\"".concat(key, "\">").concat(vditor.options.preview.theme.list[key], "</button>");
        });
        panelElement.innerHTML =
            "<div style=\"overflow: auto;max-height:".concat(window.innerHeight / 2, "px\">").concat(innerHTML, "</div>");
        panelElement.addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            if (event.target.tagName === "BUTTON") {
                hidePanel(vditor, ["subToolbar"]);
                vditor.options.preview.theme.current = event.target.getAttribute("data-type");
                (0,setContentTheme/* setContentTheme */.Z)(vditor.options.preview.theme.current, vditor.options.preview.theme.path);
                event.preventDefault();
                event.stopPropagation();
            }
        });
        _this.element.appendChild(panelElement);
        toggleSubMenu(vditor, panelElement, actionBtn, menuItem.level);
        return _this;
    }
    return ContentTheme;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Counter.ts
var Counter = /** @class */ (function () {
    function Counter(vditor) {
        this.element = document.createElement("span");
        this.element.className = "vditor-counter vditor-tooltipped vditor-tooltipped__nw";
        this.render(vditor, "");
    }
    Counter.prototype.render = function (vditor, mdText) {
        var length = mdText.endsWith("\n") ? mdText.length - 1 : mdText.length;
        if (vditor.options.counter.type === "text" && vditor[vditor.currentMode]) {
            var tempElement = vditor[vditor.currentMode].element.cloneNode(true);
            tempElement.querySelectorAll(".vditor-wysiwyg__preview").forEach(function (item) {
                item.remove();
            });
            length = tempElement.textContent.length;
        }
        if (typeof vditor.options.counter.max === "number") {
            if (length > vditor.options.counter.max) {
                this.element.className = "vditor-counter vditor-counter--error";
            }
            else {
                this.element.className = "vditor-counter";
            }
            this.element.innerHTML = "".concat(length, "/").concat(vditor.options.counter.max);
        }
        else {
            this.element.innerHTML = "".concat(length);
        }
        this.element.setAttribute("aria-label", vditor.options.counter.type);
        if (vditor.options.counter.after) {
            vditor.options.counter.after(length, {
                enable: vditor.options.counter.enable,
                max: vditor.options.counter.max,
                type: vditor.options.counter.type,
            });
        }
    };
    return Counter;
}());


;// CONCATENATED MODULE: ./src/ts/toolbar/Custom.ts
var Custom_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();



var Custom = /** @class */ (function (_super) {
    Custom_extends(Custom, _super);
    function Custom(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this.element.children[0].innerHTML = menuItem.icon;
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (event.currentTarget.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            menuItem.click(event, vditor);
        });
        return _this;
    }
    return Custom;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Devtools.ts
var Devtools_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();




var Devtools = /** @class */ (function (_super) {
    Devtools_extends(Devtools, _super);
    function Devtools(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this.element.firstElementChild.addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            var btnElement = _this.element.firstElementChild;
            if (btnElement.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            event.preventDefault();
            if (btnElement.classList.contains("vditor-menu--current")) {
                btnElement.classList.remove("vditor-menu--current");
                vditor.devtools.element.style.display = "none";
                setPadding(vditor);
            }
            else {
                btnElement.classList.add("vditor-menu--current");
                vditor.devtools.element.style.display = "block";
                setPadding(vditor);
                vditor.devtools.renderEchart(vditor);
            }
        });
        return _this;
    }
    return Devtools;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Divider.ts
var Divider = /** @class */ (function () {
    function Divider() {
        this.element = document.createElement("div");
        this.element.className = "vditor-toolbar__divider";
    }
    return Divider;
}());


;// CONCATENATED MODULE: ./src/ts/toolbar/Emoji.ts
var Emoji_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();






var Emoji = /** @class */ (function (_super) {
    Emoji_extends(Emoji, _super);
    function Emoji(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        var panelElement = document.createElement("div");
        panelElement.className = "vditor-panel vditor-panel--arrow";
        var commonEmojiHTML = "";
        Object.keys(vditor.options.hint.emoji).forEach(function (key) {
            var emojiValue = vditor.options.hint.emoji[key];
            if (emojiValue.indexOf(".") > -1) {
                commonEmojiHTML += "<button data-value=\":".concat(key, ": \" data-key=\":").concat(key, ":\"><img\ndata-value=\":").concat(key, ": \" data-key=\":").concat(key, ":\" class=\"vditor-emojis__icon\" src=\"").concat(emojiValue, "\"/></button>");
            }
            else {
                commonEmojiHTML += "<button data-value=\"".concat(emojiValue, " \"\n data-key=\"").concat(key, "\"><span class=\"vditor-emojis__icon\">").concat(emojiValue, "</span></button>");
            }
        });
        panelElement.innerHTML = "<div class=\"vditor-emojis\" style=\"max-height: ".concat(vditor.options.height === "auto" ? "auto" : vditor.options.height - 80, "px\">").concat(commonEmojiHTML, "</div><div class=\"vditor-emojis__tail\">\n    <span class=\"vditor-emojis__tip\"></span><span>").concat(vditor.options.hint.emojiTail || "", "</span>\n</div>");
        _this.element.appendChild(panelElement);
        toggleSubMenu(vditor, panelElement, _this.element.firstElementChild, menuItem.level);
        _this.bindEvent(vditor);
        return _this;
    }
    Emoji.prototype.bindEvent = function (vditor) {
        var _this = this;
        this.element.lastElementChild.addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            var btnElement = (0,hasClosestByHeadings/* hasClosestByTag */.S)(event.target, "BUTTON");
            if (btnElement) {
                event.preventDefault();
                var value = btnElement.getAttribute("data-value");
                var range = (0,selection/* getEditorRange */.zh)(vditor);
                var html = value;
                if (vditor.currentMode === "wysiwyg") {
                    html = vditor.lute.SpinVditorDOM(value);
                }
                else if (vditor.currentMode === "ir") {
                    html = vditor.lute.SpinVditorIRDOM(value);
                }
                if (value.indexOf(":") > -1 && vditor.currentMode !== "sv") {
                    var tempElement = document.createElement("div");
                    tempElement.innerHTML = html;
                    html = tempElement.firstElementChild.firstElementChild.outerHTML + " ";
                    (0,selection/* insertHTML */.oC)(html, vditor);
                }
                else {
                    range.extractContents();
                    range.insertNode(document.createTextNode(value));
                }
                range.collapse(false);
                (0,selection/* setSelectionFocus */.Hc)(range);
                _this.element.lastElementChild.style.display = "none";
                execAfterRender(vditor);
            }
        });
        this.element.lastElementChild.addEventListener("mouseover", function (event) {
            var btnElement = (0,hasClosestByHeadings/* hasClosestByTag */.S)(event.target, "BUTTON");
            if (btnElement) {
                _this.element.querySelector(".vditor-emojis__tip").innerHTML = btnElement.getAttribute("data-key");
            }
        });
    };
    return Emoji;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/export/index.ts


var download = function (vditor, content, filename) {
    var aElement = document.createElement("a");
    if ("download" in aElement) {
        aElement.download = filename;
        aElement.style.display = "none";
        aElement.href = URL.createObjectURL(new Blob([content]));
        document.body.appendChild(aElement);
        aElement.click();
        aElement.remove();
    }
    else {
        vditor.tip.show(window.VditorI18n.downloadTip, 0);
    }
};
var exportMarkdown = function (vditor) {
    var content = getMarkdown(vditor);
    download(vditor, content, content.substr(0, 10) + ".md");
};
var exportPDF = function (vditor) {
    vditor.tip.show(window.VditorI18n.generate, 3800);
    var iframe = document.querySelector("#vditorExportIframe");
    iframe.contentDocument.open();
    iframe.contentDocument.write("<link rel=\"stylesheet\" href=\"".concat(vditor.options.cdn, "/dist/index.css\"/>\n<script src=\"").concat(vditor.options.cdn, "/dist/method.min.js\"></script>\n<div id=\"preview\" style=\"width: 800px\"></div>\n<script>\nwindow.addEventListener(\"message\", (e) => {\n  if(!e.data) {\n    return;\n  }\n  Vditor.preview(document.getElementById('preview'), e.data, {\n    cdn: \"").concat(vditor.options.cdn, "\",\n    markdown: {\n      theme: ").concat(JSON.stringify(vditor.options.preview.theme), "\n    },\n    hljs: {\n      style: \"").concat(vditor.options.preview.hljs.style, "\"\n    }\n  });\n  setTimeout(() => {\n        window.print();\n    }, 3600);\n}, false);\n</script>"));
    iframe.contentDocument.close();
    setTimeout(function () {
        iframe.contentWindow.postMessage(getMarkdown(vditor), "*");
    }, 200);
};
var exportHTML = function (vditor) {
    var content = getHTML(vditor);
    var html = "<html><head><link rel=\"stylesheet\" type=\"text/css\" href=\"".concat(vditor.options.cdn, "/dist/index.css\"/>\n<script src=\"").concat(vditor.options.cdn, "/dist/js/i18n/").concat(vditor.options.lang, ".js\"></script>\n<script src=\"").concat(vditor.options.cdn, "/dist/method.min.js\"></script></head>\n<body><div class=\"vditor-reset\" id=\"preview\">").concat(content, "</div>\n<script>\n    const previewElement = document.getElementById('preview')\n    Vditor.setContentTheme('").concat(vditor.options.preview.theme.current, "', '").concat(vditor.options.preview.theme.path, "');\n    Vditor.codeRender(previewElement);\n    Vditor.highlightRender(").concat(JSON.stringify(vditor.options.preview.hljs), ", previewElement, '").concat(vditor.options.cdn, "');\n    Vditor.mathRender(previewElement, {\n        cdn: '").concat(vditor.options.cdn, "',\n        math: ").concat(JSON.stringify(vditor.options.preview.math), ",\n    });\n    Vditor.mermaidRender(previewElement, '").concat(vditor.options.cdn, "', '").concat(vditor.options.theme, "');\n    Vditor.markmapRender(previewElement, '").concat(vditor.options.cdn, "', '").concat(vditor.options.theme, "');\n    Vditor.flowchartRender(previewElement, '").concat(vditor.options.cdn, "');\n    Vditor.graphvizRender(previewElement, '").concat(vditor.options.cdn, "');\n    Vditor.chartRender(previewElement, '").concat(vditor.options.cdn, "', '").concat(vditor.options.theme, "');\n    Vditor.mindmapRender(previewElement, '").concat(vditor.options.cdn, "', '").concat(vditor.options.theme, "');\n    Vditor.abcRender(previewElement, '").concat(vditor.options.cdn, "');\n    ").concat(vditor.options.preview.render.media.enable ? 'Vditor.mediaRender(previewElement);' : "", "\n    Vditor.speechRender(previewElement);\n</script>\n<script src=\"").concat(vditor.options.cdn, "/dist/js/icons/").concat(vditor.options.icon, ".js\"></script></body></html>");
    download(vditor, html, content.substr(0, 10) + ".html");
};

;// CONCATENATED MODULE: ./src/ts/toolbar/Export.ts
var Export_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();




var Export = /** @class */ (function (_super) {
    Export_extends(Export, _super);
    function Export(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        var actionBtn = _this.element.children[0];
        var panelElement = document.createElement("div");
        panelElement.className = "vditor-hint".concat(menuItem.level === 2 ? "" : " vditor-panel--arrow");
        panelElement.innerHTML = "<button data-type=\"markdown\">Markdown</button>\n<button data-type=\"pdf\">PDF</button>\n<button data-type=\"html\">HTML</button>";
        panelElement.addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            var btnElement = event.target;
            if (btnElement.tagName === "BUTTON") {
                switch (btnElement.getAttribute("data-type")) {
                    case "markdown":
                        exportMarkdown(vditor);
                        break;
                    case "pdf":
                        exportPDF(vditor);
                        break;
                    case "html":
                        exportHTML(vditor);
                        break;
                    default:
                        break;
                }
                hidePanel(vditor, ["subToolbar"]);
                event.preventDefault();
                event.stopPropagation();
            }
        });
        _this.element.appendChild(panelElement);
        toggleSubMenu(vditor, panelElement, actionBtn, menuItem.level);
        return _this;
    }
    return Export;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Fullscreen.ts
var Fullscreen_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();



var Fullscreen = /** @class */ (function (_super) {
    Fullscreen_extends(Fullscreen, _super);
    function Fullscreen(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this._bindEvent(vditor, menuItem);
        return _this;
    }
    Fullscreen.prototype._bindEvent = function (vditor, menuItem) {
        this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (vditor.element.className.includes("vditor--fullscreen")) {
                if (!menuItem.level) {
                    this.innerHTML = menuItem.icon;
                }
                vditor.element.style.zIndex = "";
                document.body.style.overflow = "";
                vditor.element.classList.remove("vditor--fullscreen");
                Object.keys(vditor.toolbar.elements).forEach(function (key) {
                    var svgElement = vditor.toolbar.elements[key].firstChild;
                    if (svgElement) {
                        svgElement.className = svgElement.className.replace("__s", "__n");
                        vditor.options.toolbar.forEach(function (item) {
                            if (typeof item !== "string" && item.tipPosition && item.name === svgElement.dataset.type) {
                                svgElement.className = "vditor-tooltipped vditor-tooltipped__".concat(item.tipPosition);
                            }
                        });
                    }
                });
                if (vditor.counter) {
                    vditor.counter.element.className = vditor.counter.element.className.replace("__s", "__n");
                }
            }
            else {
                if (!menuItem.level) {
                    this.innerHTML = '<svg><use xlink:href="#vditor-icon-contract"></use></svg>';
                }
                vditor.element.style.zIndex = vditor.options.fullscreen.index.toString();
                document.body.style.overflow = "hidden";
                vditor.element.classList.add("vditor--fullscreen");
                Object.keys(vditor.toolbar.elements).forEach(function (key) {
                    var svgElement = vditor.toolbar.elements[key].firstChild;
                    if (svgElement) {
                        svgElement.className = svgElement.className.replace("__n", "__s");
                    }
                });
                if (vditor.counter) {
                    vditor.counter.element.className = vditor.counter.element.className.replace("__n", "__s");
                }
            }
            if (vditor.devtools) {
                vditor.devtools.renderEchart(vditor);
            }
            if (menuItem.click) {
                menuItem.click(event, vditor);
            }
            setPadding(vditor);
            setTypewriterPosition(vditor);
        });
    };
    return Fullscreen;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Headings.ts
var Headings_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();








var Headings = /** @class */ (function (_super) {
    Headings_extends(Headings, _super);
    function Headings(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        var panelElement = document.createElement("div");
        panelElement.className = "vditor-hint vditor-panel--arrow";
        panelElement.innerHTML = "<button data-tag=\"h1\" data-value=\"# \">".concat(window.VditorI18n.heading1, " ").concat((0,compatibility/* updateHotkeyTip */.ns)("&lt;⌥⌘1>"), "</button>\n<button data-tag=\"h2\" data-value=\"## \">").concat(window.VditorI18n.heading2, " &lt;").concat((0,compatibility/* updateHotkeyTip */.ns)("⌥⌘2"), "></button>\n<button data-tag=\"h3\" data-value=\"### \">").concat(window.VditorI18n.heading3, " &lt;").concat((0,compatibility/* updateHotkeyTip */.ns)("⌥⌘3"), "></button>\n<button data-tag=\"h4\" data-value=\"#### \">").concat(window.VditorI18n.heading4, " &lt;").concat((0,compatibility/* updateHotkeyTip */.ns)("⌥⌘4"), "></button>\n<button data-tag=\"h5\" data-value=\"##### \">").concat(window.VditorI18n.heading5, " &lt;").concat((0,compatibility/* updateHotkeyTip */.ns)("⌥⌘5"), "></button>\n<button data-tag=\"h6\" data-value=\"###### \">").concat(window.VditorI18n.heading6, " &lt;").concat((0,compatibility/* updateHotkeyTip */.ns)("⌥⌘6"), "></button>");
        _this.element.appendChild(panelElement);
        _this._bindEvent(vditor, panelElement);
        return _this;
    }
    Headings.prototype._bindEvent = function (vditor, panelElement) {
        var actionBtn = this.element.children[0];
        actionBtn.addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            // https://github.com/Vanessa219/vditor/issues/1391
            clearTimeout(vditor.wysiwyg.afterRenderTimeoutId);
            clearTimeout(vditor.ir.processTimeoutId);
            clearTimeout(vditor.sv.processTimeoutId);
            if (actionBtn.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            actionBtn.blur();
            if (actionBtn.classList.contains("vditor-menu--current")) {
                if (vditor.currentMode === "wysiwyg") {
                    removeHeading(vditor);
                    afterRenderEvent(vditor);
                }
                else if (vditor.currentMode === "ir") {
                    process_processHeading(vditor, "");
                }
                actionBtn.classList.remove("vditor-menu--current");
            }
            else {
                hidePanel(vditor, ["subToolbar"]);
                panelElement.style.display = "block";
            }
        });
        for (var i = 0; i < 6; i++) {
            panelElement.children.item(i).addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
                event.preventDefault();
                if (vditor.currentMode === "wysiwyg") {
                    setHeading(vditor, event.target.getAttribute("data-tag"));
                    afterRenderEvent(vditor);
                    actionBtn.classList.add("vditor-menu--current");
                }
                else if (vditor.currentMode === "ir") {
                    process_processHeading(vditor, event.target.getAttribute("data-value"));
                    actionBtn.classList.add("vditor-menu--current");
                }
                else {
                    processHeading(vditor, event.target.getAttribute("data-value"));
                }
                panelElement.style.display = "none";
            });
        }
    };
    return Headings;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Help.ts
var Help_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();


var Help = /** @class */ (function (_super) {
    Help_extends(Help, _super);
    function Help(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            vditor.tip.show("<div style=\"margin-bottom:14px;font-size: 14px;line-height: 22px;min-width:300px;max-width: 360px;display: flex;\">\n<div style=\"margin-top: 14px;flex: 1\">\n    <div>Markdown \u4F7F\u7528\u6307\u5357</div>\n    <ul style=\"list-style: none\">\n        <li><a href=\"https://ld246.com/article/1583308420519\" target=\"_blank\">\u8BED\u6CD5\u901F\u67E5\u624B\u518C</a></li>\n        <li><a href=\"https://ld246.com/article/1583129520165\" target=\"_blank\">\u57FA\u7840\u8BED\u6CD5</a></li>\n        <li><a href=\"https://ld246.com/article/1583305480675\" target=\"_blank\">\u6269\u5C55\u8BED\u6CD5</a></li>\n        <li><a href=\"https://ld246.com/article/1582778815353\" target=\"_blank\">\u952E\u76D8\u5FEB\u6377\u952E</a></li>\n    </ul>\n</div>\n<div style=\"margin-top: 14px;flex: 1\">\n    <div>Vditor \u652F\u6301</div>\n    <ul style=\"list-style: none\">\n        <li><a href=\"https://github.com/Vanessa219/vditor/issues\" target=\"_blank\">Issues</a></li>\n        <li><a href=\"https://ld246.com/tag/vditor\" target=\"_blank\">\u5B98\u65B9\u8BA8\u8BBA\u533A</a></li>\n        <li><a href=\"https://ld246.com/article/1549638745630\" target=\"_blank\">\u5F00\u53D1\u624B\u518C</a></li>\n        <li><a href=\"https://ld246.com/guide/markdown\" target=\"_blank\">\u6F14\u793A\u5730\u5740</a></li>\n    </ul>\n</div></div>", 0);
        });
        return _this;
    }
    return Help;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Indent.ts
var Indent_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();






var Indent = /** @class */ (function (_super) {
    Indent_extends(Indent, _super);
    function Indent(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED) ||
                vditor.currentMode === "sv") {
                return;
            }
            var range = (0,selection/* getEditorRange */.zh)(vditor);
            var liElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "LI");
            if (liElement) {
                listIndent(vditor, liElement, range);
            }
        });
        return _this;
    }
    return Indent;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Info.ts
var Info_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();



var Info = /** @class */ (function (_super) {
    Info_extends(Info, _super);
    function Info(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            vditor.tip.show("<div style=\"max-width: 520px; font-size: 14px;line-height: 22px;margin-bottom: 14px;\">\n<p style=\"text-align: center;margin: 14px 0\">\n    <em>\u4E0B\u4E00\u4EE3\u7684 Markdown \u7F16\u8F91\u5668\uFF0C\u4E3A\u672A\u6765\u800C\u6784\u5EFA</em>\n</p>\n<div style=\"display: flex;margin-bottom: 14px;flex-wrap: wrap;align-items: center\">\n    <img src=\"https://unpkg.com/vditor/dist/images/logo.png\" style=\"margin: 0 auto;height: 68px\"/>\n    <div>&nbsp;&nbsp;</div>\n    <div style=\"flex: 1;min-width: 250px\">\n        Vditor \u662F\u4E00\u6B3E\u6D4F\u89C8\u5668\u7AEF\u7684 Markdown \u7F16\u8F91\u5668\uFF0C\u652F\u6301\u6240\u89C1\u5373\u6240\u5F97\u3001\u5373\u65F6\u6E32\u67D3\uFF08\u7C7B\u4F3C Typora\uFF09\u548C\u5206\u5C4F\u9884\u89C8\u6A21\u5F0F\u3002\n        \u5B83\u4F7F\u7528 TypeScript \u5B9E\u73B0\uFF0C\u652F\u6301\u539F\u751F JavaScript \u4EE5\u53CA Vue\u3001React\u3001Angular \u548C Svelte \u7B49\u6846\u67B6\u3002\n    </div>\n</div>\n<div style=\"display: flex;flex-wrap: wrap;\">\n    <ul style=\"list-style: none;flex: 1;min-width:148px\">\n        <li>\n        \u9879\u76EE\u5730\u5740\uFF1A<a href=\"https://b3log.org/vditor\" target=\"_blank\">b3log.org/vditor</a>\n        </li>\n        <li>\n        \u5F00\u6E90\u534F\u8BAE\uFF1AMIT\n        </li>\n    </ul>\n    <ul style=\"list-style: none;margin-right: 18px\">\n        <li>\n        \u7EC4\u4EF6\u7248\u672C\uFF1AVditor v".concat(constants/* VDITOR_VERSION */.H, " / Lute v").concat(Lute.Version, "\n        </li>\n        <li>\n        \u8D5E\u52A9\u6350\u8D60\uFF1A<a href=\"https://ld246.com/sponsor\" target=\"_blank\">https://ld246.com/sponsor</a>\n        </li>\n    </ul>\n</div>\n</div>"), 0);
        });
        return _this;
    }
    return Info;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/InsertAfter.ts
var InsertAfter_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();




var InsertAfter = /** @class */ (function (_super) {
    InsertAfter_extends(InsertAfter, _super);
    function InsertAfter(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED) ||
                vditor.currentMode === "sv") {
                return;
            }
            insertEmptyBlock(vditor, "afterend");
        });
        return _this;
    }
    return InsertAfter;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/InsertBefore.ts
var InsertBefore_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();




var InsertBefore = /** @class */ (function (_super) {
    InsertBefore_extends(InsertBefore, _super);
    function InsertBefore(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED) ||
                vditor.currentMode === "sv") {
                return;
            }
            insertEmptyBlock(vditor, "beforebegin");
        });
        return _this;
    }
    return InsertBefore;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Outdent.ts
var Outdent_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();






var Outdent = /** @class */ (function (_super) {
    Outdent_extends(Outdent, _super);
    function Outdent(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED) ||
                vditor.currentMode === "sv") {
                return;
            }
            var range = (0,selection/* getEditorRange */.zh)(vditor);
            var liElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "LI");
            if (liElement) {
                listOutdent(vditor, liElement, range, liElement.parentElement);
            }
        });
        return _this;
    }
    return Outdent;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Outline.ts
var Outline_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();



var Outline_Outline = /** @class */ (function (_super) {
    Outline_extends(Outline, _super);
    function Outline(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        if (vditor.options.outline) {
            _this.element.firstElementChild.classList.add("vditor-menu--current");
        }
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            var btnElement = vditor.toolbar.elements.outline.firstElementChild;
            if (btnElement.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            vditor.options.outline.enable = !_this.element.firstElementChild.classList.contains("vditor-menu--current");
            vditor.outline.toggle(vditor, vditor.options.outline.enable);
        });
        return _this;
    }
    return Outline;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Preview.ts
var Preview_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();





var Preview_Preview = /** @class */ (function (_super) {
    Preview_extends(Preview, _super);
    function Preview(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this._bindEvent(vditor);
        return _this;
    }
    Preview.prototype._bindEvent = function (vditor) {
        var _this = this;
        this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            var btnElement = _this.element.firstElementChild;
            if (btnElement.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            var toolbars = constants/* Constants.EDIT_TOOLBARS.concat */.g.EDIT_TOOLBARS.concat(["both", "edit-mode", "devtools"]);
            if (btnElement.classList.contains("vditor-menu--current")) {
                btnElement.classList.remove("vditor-menu--current");
                if (vditor.currentMode === "sv") {
                    vditor.sv.element.style.display = "block";
                    if (vditor.options.preview.mode === "both") {
                        vditor.preview.element.style.display = "block";
                    }
                    else {
                        vditor.preview.element.style.display = "none";
                    }
                }
                else {
                    vditor[vditor.currentMode].element.parentElement.style.display = "block";
                    vditor.preview.element.style.display = "none";
                }
                enableToolbar(vditor.toolbar.elements, toolbars);
                vditor.outline.render(vditor);
            }
            else {
                disableToolbar(vditor.toolbar.elements, toolbars);
                vditor.preview.element.style.display = "block";
                if (vditor.currentMode === "sv") {
                    vditor.sv.element.style.display = "none";
                }
                else {
                    vditor[vditor.currentMode].element.parentElement.style.display = "none";
                }
                vditor.preview.render(vditor);
                btnElement.classList.add("vditor-menu--current");
                hidePanel(vditor, ["subToolbar", "hint", "popover"]);
                setTimeout(function () {
                    vditor.outline.render(vditor);
                }, vditor.options.preview.delay + 10);
            }
            setPadding(vditor);
        });
    };
    return Preview;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/util/RecordMedia.ts
var RecordMedia = /** @class */ (function () {
    function RecordMedia(e) {
        this.SAMPLE_RATE = 5000; // 44100 suggested by demos;
        this.isRecording = false;
        this.readyFlag = false;
        this.leftChannel = [];
        this.rightChannel = [];
        this.recordingLength = 0;
        var context;
        // creates the audio context
        if (typeof AudioContext !== "undefined") {
            context = new AudioContext();
        }
        else if (webkitAudioContext) {
            context = new webkitAudioContext();
        }
        else {
            return;
        }
        this.DEFAULT_SAMPLE_RATE = context.sampleRate;
        // creates a gain node
        var volume = context.createGain();
        // creates an audio node from the microphone incoming stream
        var audioInput = context.createMediaStreamSource(e);
        // connect the stream to the gain node
        audioInput.connect(volume);
        /* From the spec: The size of the buffer controls how frequently the audioprocess event is
         dispatched and how many sample-frames need to be processed each call.
         Lower values for buffer size will result in a lower (better) latency.
         Higher values will be necessary to avoid audio breakup and glitches */
        this.recorder = context.createScriptProcessor(2048, 2, 1);
        // The onaudioprocess event needs to be defined externally, so make sure it is not set:
        this.recorder.onaudioprocess = null;
        // we connect the recorder
        volume.connect(this.recorder);
        this.recorder.connect(context.destination);
        this.readyFlag = true;
    }
    // Publicly accessible methods:
    RecordMedia.prototype.cloneChannelData = function (leftChannelData, rightChannelData) {
        this.leftChannel.push(new Float32Array(leftChannelData));
        this.rightChannel.push(new Float32Array(rightChannelData));
        this.recordingLength += 2048;
    };
    RecordMedia.prototype.startRecordingNewWavFile = function () {
        if (this.readyFlag) {
            this.isRecording = true;
            this.leftChannel.length = this.rightChannel.length = 0;
            this.recordingLength = 0;
        }
    };
    RecordMedia.prototype.stopRecording = function () {
        this.isRecording = false;
    };
    RecordMedia.prototype.buildWavFileBlob = function () {
        // we flat the left and right channels down
        var leftBuffer = this.mergeBuffers(this.leftChannel);
        var rightBuffer = this.mergeBuffers(this.rightChannel);
        // Interleave the left and right channels together:
        var interleaved = new Float32Array(leftBuffer.length);
        for (var i = 0; i < leftBuffer.length; ++i) {
            interleaved[i] = 0.5 * (leftBuffer[i] + rightBuffer[i]);
        }
        // Downsample the audio data if necessary:
        if (this.DEFAULT_SAMPLE_RATE > this.SAMPLE_RATE) {
            interleaved = this.downSampleBuffer(interleaved, this.SAMPLE_RATE);
        }
        var totalByteCount = (44 + interleaved.length * 2);
        var buffer = new ArrayBuffer(totalByteCount);
        var view = new DataView(buffer);
        // Build the RIFF chunk descriptor:
        this.writeUTFBytes(view, 0, "RIFF");
        view.setUint32(4, totalByteCount, true);
        this.writeUTFBytes(view, 8, "WAVE");
        // Build the FMT sub-chunk:
        this.writeUTFBytes(view, 12, "fmt "); // subchunk1 ID is format
        view.setUint32(16, 16, true); // The sub-chunk size is 16.
        view.setUint16(20, 1, true); // The audio format is 1.
        view.setUint16(22, 1, true); // Number of interleaved channels.
        view.setUint32(24, this.SAMPLE_RATE, true); // Sample rate.
        view.setUint32(28, this.SAMPLE_RATE * 2, true); // Byte rate.
        view.setUint16(32, 2, true); // Block align
        view.setUint16(34, 16, true); // Bits per sample.
        // Build the data sub-chunk:
        var subChunk2ByteCount = interleaved.length * 2;
        this.writeUTFBytes(view, 36, "data");
        view.setUint32(40, subChunk2ByteCount, true);
        // Write the PCM samples to the view:
        var lng = interleaved.length;
        var index = 44;
        var volume = 1;
        for (var j = 0; j < lng; j++) {
            view.setInt16(index, interleaved[j] * (0x7FFF * volume), true);
            index += 2;
        }
        return new Blob([view], { type: "audio/wav" });
    };
    RecordMedia.prototype.downSampleBuffer = function (buffer, rate) {
        if (rate === this.DEFAULT_SAMPLE_RATE) {
            return buffer;
        }
        if (rate > this.DEFAULT_SAMPLE_RATE) {
            // throw "downsampling rate show be smaller than original sample rate";
            return buffer;
        }
        var sampleRateRatio = this.DEFAULT_SAMPLE_RATE / rate;
        var newLength = Math.round(buffer.length / sampleRateRatio);
        var result = new Float32Array(newLength);
        var offsetResult = 0;
        var offsetBuffer = 0;
        while (offsetResult < result.length) {
            var nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
            var accum = 0;
            var count = 0;
            for (var i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
                accum += buffer[i];
                count++;
            }
            result[offsetResult] = accum / count;
            offsetResult++;
            offsetBuffer = nextOffsetBuffer;
        }
        return result;
    };
    RecordMedia.prototype.mergeBuffers = function (desiredChannelBuffer) {
        var result = new Float32Array(this.recordingLength);
        var offset = 0;
        var lng = desiredChannelBuffer.length;
        for (var i = 0; i < lng; ++i) {
            var buffer = desiredChannelBuffer[i];
            result.set(buffer, offset);
            offset += buffer.length;
        }
        return result;
    };
    RecordMedia.prototype.writeUTFBytes = function (view, offset, value) {
        var lng = value.length;
        for (var i = 0; i < lng; i++) {
            view.setUint8(offset + i, value.charCodeAt(i));
        }
    };
    return RecordMedia;
}());


;// CONCATENATED MODULE: ./src/ts/toolbar/Record.ts
var Record_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();





var Record = /** @class */ (function (_super) {
    Record_extends(Record, _super);
    function Record(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        _this._bindEvent(vditor);
        return _this;
    }
    Record.prototype._bindEvent = function (vditor) {
        var _this = this;
        var mediaRecorder;
        this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            var editorElement = vditor[vditor.currentMode].element;
            if (!mediaRecorder) {
                navigator.mediaDevices.getUserMedia({ audio: true }).then(function (mediaStream) {
                    mediaRecorder = new RecordMedia(mediaStream);
                    mediaRecorder.recorder.onaudioprocess = function (e) {
                        // Do nothing if not recording:
                        if (!mediaRecorder.isRecording) {
                            return;
                        }
                        // Copy the data from the input buffers;
                        var left = e.inputBuffer.getChannelData(0);
                        var right = e.inputBuffer.getChannelData(1);
                        mediaRecorder.cloneChannelData(left, right);
                    };
                    mediaRecorder.startRecordingNewWavFile();
                    vditor.tip.show(window.VditorI18n.recording);
                    editorElement.setAttribute("contenteditable", "false");
                    _this.element.children[0].classList.add("vditor-menu--current");
                }).catch(function () {
                    vditor.tip.show(window.VditorI18n["record-tip"]);
                });
                return;
            }
            if (mediaRecorder.isRecording) {
                mediaRecorder.stopRecording();
                vditor.tip.hide();
                var file = new File([mediaRecorder.buildWavFileBlob()], "record".concat((new Date()).getTime(), ".wav"), { type: "video/webm" });
                uploadFiles(vditor, [file]);
                _this.element.children[0].classList.remove("vditor-menu--current");
            }
            else {
                vditor.tip.show(window.VditorI18n.recording);
                editorElement.setAttribute("contenteditable", "false");
                mediaRecorder.startRecordingNewWavFile();
                _this.element.children[0].classList.add("vditor-menu--current");
            }
        });
    };
    return Record;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Redo.ts
var Redo_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();




var Redo = /** @class */ (function (_super) {
    Redo_extends(Redo, _super);
    function Redo(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        disableToolbar({ redo: _this.element }, ["redo"]);
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            vditor.undo.redo(vditor);
        });
        return _this;
    }
    return Redo;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Undo.ts
var Undo_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();




var Undo = /** @class */ (function (_super) {
    Undo_extends(Undo, _super);
    function Undo(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        disableToolbar({ undo: _this.element }, ["undo"]);
        _this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            event.preventDefault();
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                return;
            }
            vditor.undo.undo(vditor);
        });
        return _this;
    }
    return Undo;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/Upload.ts
var Upload_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();




var Upload_Upload = /** @class */ (function (_super) {
    Upload_extends(Upload, _super);
    function Upload(vditor, menuItem) {
        var _this = _super.call(this, vditor, menuItem) || this;
        var inputHTML = '<input type="file"';
        if (vditor.options.upload.multiple) {
            inputHTML += ' multiple="multiple"';
        }
        if (vditor.options.upload.accept) {
            inputHTML += " accept=\"".concat(vditor.options.upload.accept, "\"");
        }
        _this.element.children[0].innerHTML = "".concat((menuItem.icon || '<svg><use xlink:href="#vditor-icon-upload"></use></svg>')).concat(inputHTML, ">");
        _this._bindEvent(vditor);
        return _this;
    }
    Upload.prototype._bindEvent = function (vditor) {
        var _this = this;
        this.element.children[0].addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                event.stopPropagation();
                event.preventDefault();
                return;
            }
        });
        this.element.querySelector("input").addEventListener("change", function (event) {
            if (_this.element.firstElementChild.classList.contains(constants/* Constants.CLASS_MENU_DISABLED */.g.CLASS_MENU_DISABLED)) {
                event.stopPropagation();
                event.preventDefault();
                return;
            }
            if (event.target.files.length === 0) {
                return;
            }
            uploadFiles(vditor, event.target.files, event.target);
        });
    };
    return Upload;
}(MenuItem));


;// CONCATENATED MODULE: ./src/ts/toolbar/index.ts




























var Toolbar = /** @class */ (function () {
    function Toolbar(vditor) {
        var _this = this;
        var options = vditor.options;
        this.elements = {};
        this.element = document.createElement("div");
        this.element.className = "vditor-toolbar";
        options.toolbar.forEach(function (menuItem, i) {
            var itemElement = _this.genItem(vditor, menuItem, i);
            _this.element.appendChild(itemElement);
            if (menuItem.toolbar) {
                var panelElement_1 = document.createElement("div");
                panelElement_1.className = "vditor-hint vditor-panel--arrow";
                panelElement_1.addEventListener((0,compatibility/* getEventName */.Le)(), function (event) {
                    panelElement_1.style.display = "none";
                });
                menuItem.toolbar.forEach(function (subMenuItem, subI) {
                    subMenuItem.level = 2;
                    panelElement_1.appendChild(_this.genItem(vditor, subMenuItem, i + subI));
                });
                itemElement.appendChild(panelElement_1);
                toggleSubMenu(vditor, panelElement_1, itemElement.children[0], 2);
            }
        });
        if (vditor.options.toolbarConfig.hide) {
            this.element.classList.add("vditor-toolbar--hide");
        }
        if (vditor.options.toolbarConfig.pin) {
            this.element.classList.add("vditor-toolbar--pin");
        }
        if (vditor.options.counter.enable) {
            vditor.counter = new Counter(vditor);
            this.element.appendChild(vditor.counter.element);
        }
    }
    Toolbar.prototype.updateConfig = function (vditor, options) {
        vditor.options.toolbarConfig = Object.assign({
            hide: false,
            pin: false,
        }, options);
        if (vditor.options.toolbarConfig.hide) {
            this.element.classList.add("vditor-toolbar--hide");
        }
        else {
            this.element.classList.remove("vditor-toolbar--hide");
        }
        if (vditor.options.toolbarConfig.pin) {
            this.element.classList.add("vditor-toolbar--pin");
        }
        else {
            this.element.classList.remove("vditor-toolbar--pin");
        }
    };
    Toolbar.prototype.genItem = function (vditor, menuItem, index) {
        var menuItemObj;
        switch (menuItem.name) {
            case "bold":
            case "italic":
            case "more":
            case "strike":
            case "line":
            case "quote":
            case "list":
            case "ordered-list":
            case "check":
            case "code":
            case "inline-code":
            case "link":
            case "table":
                menuItemObj = new MenuItem(vditor, menuItem);
                break;
            case "emoji":
                menuItemObj = new Emoji(vditor, menuItem);
                break;
            case "headings":
                menuItemObj = new Headings(vditor, menuItem);
                break;
            case "|":
                menuItemObj = new Divider();
                break;
            case "br":
                menuItemObj = new Br();
                break;
            case "undo":
                menuItemObj = new Undo(vditor, menuItem);
                break;
            case "redo":
                menuItemObj = new Redo(vditor, menuItem);
                break;
            case "help":
                menuItemObj = new Help(vditor, menuItem);
                break;
            case "both":
                menuItemObj = new Both(vditor, menuItem);
                break;
            case "preview":
                menuItemObj = new Preview_Preview(vditor, menuItem);
                break;
            case "fullscreen":
                menuItemObj = new Fullscreen(vditor, menuItem);
                break;
            case "upload":
                menuItemObj = new Upload_Upload(vditor, menuItem);
                break;
            case "record":
                menuItemObj = new Record(vditor, menuItem);
                break;
            case "info":
                menuItemObj = new Info(vditor, menuItem);
                break;
            case "edit-mode":
                menuItemObj = new EditMode(vditor, menuItem);
                break;
            case "devtools":
                menuItemObj = new Devtools(vditor, menuItem);
                break;
            case "outdent":
                menuItemObj = new Outdent(vditor, menuItem);
                break;
            case "indent":
                menuItemObj = new Indent(vditor, menuItem);
                break;
            case "outline":
                menuItemObj = new Outline_Outline(vditor, menuItem);
                break;
            case "insert-after":
                menuItemObj = new InsertAfter(vditor, menuItem);
                break;
            case "insert-before":
                menuItemObj = new InsertBefore(vditor, menuItem);
                break;
            case "code-theme":
                menuItemObj = new CodeTheme(vditor, menuItem);
                break;
            case "content-theme":
                menuItemObj = new ContentTheme(vditor, menuItem);
                break;
            case "export":
                menuItemObj = new Export(vditor, menuItem);
                break;
            default:
                menuItemObj = new Custom(vditor, menuItem);
                break;
        }
        if (!menuItemObj) {
            return;
        }
        var key = menuItem.name;
        if (key === "br" || key === "|") {
            key = key + index;
        }
        this.elements[key] = menuItemObj.element;
        return menuItemObj.element;
    };
    return Toolbar;
}());


// EXTERNAL MODULE: ./node_modules/.pnpm/diff-match-patch@1.0.5/node_modules/diff-match-patch/index.js
var diff_match_patch = __webpack_require__(85);
;// CONCATENATED MODULE: ./src/ts/undo/index.ts









var undo_Undo = /** @class */ (function () {
    function Undo() {
        this.stackSize = 50;
        this.resetStack();
        // @ts-ignore
        this.dmp = new diff_match_patch();
    }
    Undo.prototype.clearStack = function (vditor) {
        this.resetStack();
        this.resetIcon(vditor);
    };
    Undo.prototype.resetIcon = function (vditor) {
        if (!vditor.toolbar) {
            return;
        }
        if (this[vditor.currentMode].undoStack.length > 1) {
            enableToolbar(vditor.toolbar.elements, ["undo"]);
        }
        else {
            disableToolbar(vditor.toolbar.elements, ["undo"]);
        }
        if (this[vditor.currentMode].redoStack.length !== 0) {
            enableToolbar(vditor.toolbar.elements, ["redo"]);
        }
        else {
            disableToolbar(vditor.toolbar.elements, ["redo"]);
        }
    };
    Undo.prototype.undo = function (vditor) {
        if (vditor[vditor.currentMode].element.getAttribute("contenteditable") === "false") {
            return;
        }
        if (this[vditor.currentMode].undoStack.length < 2) {
            return;
        }
        var state = this[vditor.currentMode].undoStack.pop();
        if (!state) {
            return;
        }
        this[vditor.currentMode].redoStack.push(state);
        this.renderDiff(state, vditor);
        this[vditor.currentMode].hasUndo = true;
        // undo 操作后，需要关闭 hint
        hidePanel(vditor, ["hint"]);
    };
    Undo.prototype.redo = function (vditor) {
        if (vditor[vditor.currentMode].element.getAttribute("contenteditable") === "false") {
            return;
        }
        var state = this[vditor.currentMode].redoStack.pop();
        if (!state) {
            return;
        }
        this[vditor.currentMode].undoStack.push(state);
        this.renderDiff(state, vditor, true);
    };
    Undo.prototype.recordFirstPosition = function (vditor, event) {
        if (getSelection().rangeCount === 0) {
            return;
        }
        if (this[vditor.currentMode].undoStack.length !== 1 || this[vditor.currentMode].undoStack[0].length === 0 ||
            this[vditor.currentMode].redoStack.length > 0) {
            return;
        }
        if ((0,compatibility/* isFirefox */.vU)() && event.key === "Backspace") {
            // Firefox 第一次删除无效
            return;
        }
        if ((0,compatibility/* isSafari */.G6)()) {
            // Safari keydown 在 input 之后，不需要重复记录历史
            return;
        }
        var text = this.addCaret(vditor);
        if (text.replace("<wbr>", "").replace(" vditor-ir__node--expand", "")
            !== this[vditor.currentMode].undoStack[0][0].diffs[0][1].replace("<wbr>", "")) {
            // 当还不没有存入 undo 栈时，按下 ctrl 后会覆盖 lastText
            return;
        }
        this[vditor.currentMode].undoStack[0][0].diffs[0][1] = text;
        this[vditor.currentMode].lastText = text;
        // 不能添加 setSelectionFocus(cloneRange); 否则 windows chrome 首次输入会烂
    };
    Undo.prototype.addToUndoStack = function (vditor) {
        // afterRenderEvent.ts 已经 debounce
        var text = this.addCaret(vditor, true);
        var diff = this.dmp.diff_main(text, this[vditor.currentMode].lastText, true);
        var patchList = this.dmp.patch_make(text, this[vditor.currentMode].lastText, diff);
        if (patchList.length === 0 && this[vditor.currentMode].undoStack.length > 0) {
            return;
        }
        this[vditor.currentMode].lastText = text;
        this[vditor.currentMode].undoStack.push(patchList);
        if (this[vditor.currentMode].undoStack.length > this.stackSize) {
            this[vditor.currentMode].undoStack.shift();
        }
        if (this[vditor.currentMode].hasUndo) {
            this[vditor.currentMode].redoStack = [];
            this[vditor.currentMode].hasUndo = false;
            disableToolbar(vditor.toolbar.elements, ["redo"]);
        }
        if (this[vditor.currentMode].undoStack.length > 1) {
            enableToolbar(vditor.toolbar.elements, ["undo"]);
        }
    };
    Undo.prototype.renderDiff = function (state, vditor, isRedo) {
        if (isRedo === void 0) { isRedo = false; }
        var text;
        if (isRedo) {
            var redoPatchList = this.dmp.patch_deepCopy(state).reverse();
            redoPatchList.forEach(function (patch) {
                patch.diffs.forEach(function (diff) {
                    diff[0] = -diff[0];
                });
            });
            text = this.dmp.patch_apply(redoPatchList, this[vditor.currentMode].lastText)[0];
        }
        else {
            text = this.dmp.patch_apply(state, this[vditor.currentMode].lastText)[0];
        }
        this[vditor.currentMode].lastText = text;
        vditor[vditor.currentMode].element.innerHTML = text;
        if (vditor.currentMode !== "sv") {
            vditor[vditor.currentMode].element.querySelectorAll(".vditor-".concat(vditor.currentMode, "__preview[data-render='2']"))
                .forEach(function (blockElement) {
                processCodeRender(blockElement, vditor);
            });
        }
        if (!vditor[vditor.currentMode].element.querySelector("wbr")) {
            // Safari 第一次输入没有光标，需手动定位到结尾
            var range = getSelection().getRangeAt(0);
            range.setEndBefore(vditor[vditor.currentMode].element);
            range.collapse(false);
        }
        else {
            (0,selection/* setRangeByWbr */.ib)(vditor[vditor.currentMode].element, vditor[vditor.currentMode].element.ownerDocument.createRange());
            scrollCenter(vditor);
        }
        renderToc(vditor);
        execAfterRender(vditor, {
            enableAddUndoStack: false,
            enableHint: false,
            enableInput: true,
        });
        highlightToolbar(vditor);
        vditor[vditor.currentMode].element.querySelectorAll(".vditor-".concat(vditor.currentMode, "__preview[data-render='2']"))
            .forEach(function (item) {
            processCodeRender(item, vditor);
        });
        if (this[vditor.currentMode].undoStack.length > 1) {
            enableToolbar(vditor.toolbar.elements, ["undo"]);
        }
        else {
            disableToolbar(vditor.toolbar.elements, ["undo"]);
        }
        if (this[vditor.currentMode].redoStack.length !== 0) {
            enableToolbar(vditor.toolbar.elements, ["redo"]);
        }
        else {
            disableToolbar(vditor.toolbar.elements, ["redo"]);
        }
    };
    Undo.prototype.resetStack = function () {
        this.ir = {
            hasUndo: false,
            lastText: "",
            redoStack: [],
            undoStack: [],
        };
        this.sv = {
            hasUndo: false,
            lastText: "",
            redoStack: [],
            undoStack: [],
        };
        this.wysiwyg = {
            hasUndo: false,
            lastText: "",
            redoStack: [],
            undoStack: [],
        };
    };
    Undo.prototype.addCaret = function (vditor, setFocus) {
        if (setFocus === void 0) { setFocus = false; }
        var cloneRange;
        if (getSelection().rangeCount !== 0 && !vditor[vditor.currentMode].element.querySelector("wbr")) {
            var range = getSelection().getRangeAt(0);
            if (vditor[vditor.currentMode].element.contains(range.startContainer)) {
                cloneRange = range.cloneRange();
                var wbrElement = document.createElement("span");
                wbrElement.className = "vditor-wbr";
                range.insertNode(wbrElement);
            }
        }
        // 移除数学公式、echart 渲染 https://github.com/siyuan-note/siyuan/issues/537
        var cloneElement = vditor.ir.element.cloneNode(true);
        cloneElement.querySelectorAll(".vditor-".concat(vditor.currentMode, "__preview[data-render='1']"))
            .forEach(function (item) {
            if (!item.firstElementChild) {
                return;
            }
            if (item.firstElementChild.classList.contains("language-echarts") ||
                item.firstElementChild.classList.contains("language-plantuml") ||
                item.firstElementChild.classList.contains("language-mindmap")) {
                item.firstElementChild.removeAttribute("_echarts_instance_");
                item.firstElementChild.removeAttribute("data-processed");
                item.firstElementChild.innerHTML = item.previousElementSibling.firstElementChild.innerHTML;
                item.setAttribute("data-render", "2");
            }
            else if (item.firstElementChild.classList.contains("language-math")) {
                item.setAttribute("data-render", "2");
                item.firstElementChild.textContent = item.firstElementChild.getAttribute("data-math");
                item.firstElementChild.removeAttribute("data-math");
            }
        });
        var text = vditor[vditor.currentMode].element.innerHTML;
        vditor[vditor.currentMode].element.querySelectorAll(".vditor-wbr").forEach(function (item) {
            item.remove();
            // 使用 item.outerHTML = "" 会产生 https://github.com/Vanessa219/vditor/pull/686;
        });
        if (setFocus && cloneRange) {
            (0,selection/* setSelectionFocus */.Hc)(cloneRange);
        }
        return text.replace('<span class="vditor-wbr"></span>', "<wbr>");
    };
    return Undo;
}());


// EXTERNAL MODULE: ./src/ts/util/merge.ts
var merge = __webpack_require__(2);
;// CONCATENATED MODULE: ./src/ts/util/Options.ts


var Options = /** @class */ (function () {
    function Options(options) {
        this.defaultOptions = {
            rtl: false,
            after: undefined,
            cache: {
                enable: true,
            },
            cdn: constants/* Constants.CDN */.g.CDN,
            classes: {
                preview: "",
            },
            comment: {
                enable: false,
            },
            counter: {
                enable: false,
                type: "markdown",
            },
            customRenders: [],
            debugger: false,
            fullscreen: {
                index: 90,
            },
            height: "auto",
            hint: {
                delay: 200,
                emoji: {
                    "+1": "👍",
                    "-1": "👎",
                    "confused": "😕",
                    "eyes": "👀️",
                    "heart": "❤️",
                    "rocket": "🚀️",
                    "smile": "😄",
                    "tada": "🎉️",
                },
                emojiPath: "".concat(constants/* Constants.CDN */.g.CDN, "/dist/images/emoji"),
                extend: [],
                parse: true,
            },
            icon: "ant",
            lang: "zh_CN",
            mode: "ir",
            outline: {
                enable: false,
                position: "left",
            },
            placeholder: "",
            preview: {
                actions: ["desktop", "tablet", "mobile", "mp-wechat", "zhihu"],
                delay: 1000,
                hljs: constants/* Constants.HLJS_OPTIONS */.g.HLJS_OPTIONS,
                markdown: constants/* Constants.MARKDOWN_OPTIONS */.g.MARKDOWN_OPTIONS,
                math: constants/* Constants.MATH_OPTIONS */.g.MATH_OPTIONS,
                maxWidth: 800,
                mode: "both",
                theme: constants/* Constants.THEME_OPTIONS */.g.THEME_OPTIONS,
                render: {
                    media: {
                        enable: true,
                    }
                }
            },
            link: {
                isOpen: true,
            },
            image: {
                isPreview: true,
            },
            resize: {
                enable: false,
                position: "bottom",
            },
            theme: "classic",
            toolbar: [
                "emoji",
                "headings",
                "bold",
                "italic",
                "strike",
                "link",
                "|",
                "list",
                "ordered-list",
                "check",
                "outdent",
                "indent",
                "|",
                "quote",
                "line",
                "code",
                "inline-code",
                "insert-before",
                "insert-after",
                "|",
                "upload",
                "record",
                "table",
                "|",
                "undo",
                "redo",
                "|",
                "fullscreen",
                "edit-mode",
                {
                    name: "more",
                    toolbar: [
                        "both",
                        "code-theme",
                        "content-theme",
                        "export",
                        "outline",
                        "preview",
                        "devtools",
                        "info",
                        "help",
                    ],
                },
            ],
            toolbarConfig: {
                hide: false,
                pin: false,
            },
            typewriterMode: false,
            undoDelay: 800,
            upload: {
                extraData: {},
                fieldName: "file[]",
                filename: function (name) { return name.replace(/\W/g, ""); },
                linkToImgUrl: "",
                max: 10 * 1024 * 1024,
                multiple: true,
                url: "",
                withCredentials: false,
            },
            value: "",
            width: "auto",
        };
        this.options = options;
    }
    Options.prototype.merge = function () {
        var _a, _b, _c, _d, _e, _f, _g, _h, _j;
        if (this.options) {
            if (this.options.toolbar) {
                this.options.toolbar = this.mergeToolbar(this.options.toolbar);
            }
            else {
                this.options.toolbar = this.mergeToolbar(this.defaultOptions.toolbar);
            }
            if ((_b = (_a = this.options.preview) === null || _a === void 0 ? void 0 : _a.theme) === null || _b === void 0 ? void 0 : _b.list) {
                this.defaultOptions.preview.theme.list = this.options.preview.theme.list;
            }
            if ((_e = (_d = (_c = this.options.preview) === null || _c === void 0 ? void 0 : _c.render) === null || _d === void 0 ? void 0 : _d.media) === null || _e === void 0 ? void 0 : _e.enable) {
                this.defaultOptions.preview.render.media.enable = this.options.preview.render.media.enable;
            }
            if ((_f = this.options.hint) === null || _f === void 0 ? void 0 : _f.emoji) {
                this.defaultOptions.hint.emoji = this.options.hint.emoji;
            }
            if (this.options.comment) {
                this.defaultOptions.comment = this.options.comment;
            }
            if (this.options.cdn) {
                if (!((_h = (_g = this.options.preview) === null || _g === void 0 ? void 0 : _g.theme) === null || _h === void 0 ? void 0 : _h.path)) {
                    this.defaultOptions.preview.theme.path = "".concat(this.options.cdn, "/dist/css/content-theme");
                }
                if (!((_j = this.options.hint) === null || _j === void 0 ? void 0 : _j.emojiPath)) {
                    this.defaultOptions.hint.emojiPath = "".concat(this.options.cdn, "/dist/images/emoji");
                }
            }
        }
        var mergedOptions = (0,merge/* merge */.T)(this.defaultOptions, this.options);
        if (mergedOptions.cache.enable && !mergedOptions.cache.id) {
            throw new Error("need options.cache.id, see https://ld246.com/article/1549638745630#options");
        }
        return mergedOptions;
    };
    Options.prototype.mergeToolbar = function (toolbar) {
        var _this = this;
        var toolbarItem = [
            {
                icon: '<svg><use xlink:href="#vditor-icon-export"></use></svg>',
                name: "export",
                tipPosition: "ne",
            },
            {
                hotkey: "⌘E",
                icon: '<svg><use xlink:href="#vditor-icon-emoji"></use></svg>',
                name: "emoji",
                tipPosition: "ne",
            },
            {
                hotkey: "⌘H",
                icon: '<svg><use xlink:href="#vditor-icon-headings"></use></svg>',
                name: "headings",
                tipPosition: "ne",
            },
            {
                hotkey: "⌘B",
                icon: '<svg><use xlink:href="#vditor-icon-bold"></use></svg>',
                name: "bold",
                prefix: "**",
                suffix: "**",
                tipPosition: "ne",
            },
            {
                hotkey: "⌘I",
                icon: '<svg><use xlink:href="#vditor-icon-italic"></use></svg>',
                name: "italic",
                prefix: "*",
                suffix: "*",
                tipPosition: "ne",
            },
            {
                hotkey: "⌘D",
                icon: '<svg><use xlink:href="#vditor-icon-strike"></use></svg>',
                name: "strike",
                prefix: "~~",
                suffix: "~~",
                tipPosition: "ne",
            },
            {
                hotkey: "⌘K",
                icon: '<svg><use xlink:href="#vditor-icon-link"></use></svg>',
                name: "link",
                prefix: "[",
                suffix: "](https://)",
                tipPosition: "n",
            },
            {
                name: "|",
            },
            {
                hotkey: "⌘L",
                icon: '<svg><use xlink:href="#vditor-icon-list"></use></svg>',
                name: "list",
                prefix: "* ",
                tipPosition: "n",
            },
            {
                hotkey: "⌘O",
                icon: '<svg><use xlink:href="#vditor-icon-ordered-list"></use></svg>',
                name: "ordered-list",
                prefix: "1. ",
                tipPosition: "n",
            },
            {
                hotkey: "⌘J",
                icon: '<svg><use xlink:href="#vditor-icon-check"></use></svg>',
                name: "check",
                prefix: "* [ ] ",
                tipPosition: "n",
            },
            {
                hotkey: "⇧⌘I",
                icon: '<svg><use xlink:href="#vditor-icon-outdent"></use></svg>',
                name: "outdent",
                tipPosition: "n",
            },
            {
                hotkey: "⇧⌘O",
                icon: '<svg><use xlink:href="#vditor-icon-indent"></use></svg>',
                name: "indent",
                tipPosition: "n",
            },
            {
                name: "|",
            },
            {
                hotkey: "⌘;",
                icon: '<svg><use xlink:href="#vditor-icon-quote"></use></svg>',
                name: "quote",
                prefix: "> ",
                tipPosition: "n",
            },
            {
                hotkey: "⇧⌘H",
                icon: '<svg><use xlink:href="#vditor-icon-line"></use></svg>',
                name: "line",
                prefix: "---",
                tipPosition: "n",
            },
            {
                hotkey: "⌘U",
                icon: '<svg><use xlink:href="#vditor-icon-code"></use></svg>',
                name: "code",
                prefix: "```",
                suffix: "\n```",
                tipPosition: "n",
            },
            {
                hotkey: "⌘G",
                icon: '<svg><use xlink:href="#vditor-icon-inline-code"></use></svg>',
                name: "inline-code",
                prefix: "`",
                suffix: "`",
                tipPosition: "n",
            },
            {
                hotkey: "⇧⌘B",
                icon: '<svg><use xlink:href="#vditor-icon-before"></use></svg>',
                name: "insert-before",
                tipPosition: "n",
            },
            {
                hotkey: "⇧⌘E",
                icon: '<svg><use xlink:href="#vditor-icon-after"></use></svg>',
                name: "insert-after",
                tipPosition: "n",
            },
            {
                name: "|",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-upload"></use></svg>',
                name: "upload",
                tipPosition: "n",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-record"></use></svg>',
                name: "record",
                tipPosition: "n",
            },
            {
                hotkey: "⌘M",
                icon: '<svg><use xlink:href="#vditor-icon-table"></use></svg>',
                name: "table",
                prefix: "| col1",
                suffix: " | col2 | col3 |\n| --- | --- | --- |\n|  |  |  |\n|  |  |  |",
                tipPosition: "n",
            },
            {
                name: "|",
            },
            {
                hotkey: "⌘Z",
                icon: '<svg><use xlink:href="#vditor-icon-undo"></use></svg>',
                name: "undo",
                tipPosition: "nw",
            },
            {
                hotkey: "⌘Y",
                icon: '<svg><use xlink:href="#vditor-icon-redo"></use></svg>',
                name: "redo",
                tipPosition: "nw",
            },
            {
                name: "|",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-more"></use></svg>',
                name: "more",
                tipPosition: "e",
            },
            {
                hotkey: "⌘'",
                icon: '<svg><use xlink:href="#vditor-icon-fullscreen"></use></svg>',
                name: "fullscreen",
                tipPosition: "nw",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-edit"></use></svg>',
                name: "edit-mode",
                tipPosition: "nw",
            },
            {
                hotkey: "⌘P",
                icon: '<svg><use xlink:href="#vditor-icon-both"></use></svg>',
                name: "both",
                tipPosition: "nw",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-preview"></use></svg>',
                name: "preview",
                tipPosition: "nw",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-align-center"></use></svg>',
                name: "outline",
                tipPosition: "nw",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-theme"></use></svg>',
                name: "content-theme",
                tipPosition: "nw",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-code-theme"></use></svg>',
                name: "code-theme",
                tipPosition: "nw",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-bug"></use></svg>',
                name: "devtools",
                tipPosition: "nw",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-info"></use></svg>',
                name: "info",
                tipPosition: "nw",
            },
            {
                icon: '<svg><use xlink:href="#vditor-icon-help"></use></svg>',
                name: "help",
                tipPosition: "nw",
            },
            {
                name: "br",
            },
        ];
        var toolbarResult = [];
        toolbar.forEach(function (menuItem) {
            var currentMenuItem = menuItem;
            toolbarItem.forEach(function (defaultMenuItem) {
                if (typeof menuItem === "string" &&
                    defaultMenuItem.name === menuItem) {
                    currentMenuItem = defaultMenuItem;
                }
                if (typeof menuItem === "object" &&
                    defaultMenuItem.name === menuItem.name) {
                    currentMenuItem = Object.assign({}, defaultMenuItem, menuItem);
                }
            });
            if (menuItem.toolbar) {
                currentMenuItem.toolbar = _this.mergeToolbar(menuItem.toolbar);
            }
            toolbarResult.push(currentMenuItem);
        });
        return toolbarResult;
    };
    return Options;
}());


;// CONCATENATED MODULE: ./src/ts/wysiwyg/index.ts















var WYSIWYG = /** @class */ (function () {
    function WYSIWYG(vditor) {
        var _this = this;
        this.composingLock = false;
        this.commentIds = [];
        var divElement = document.createElement("div");
        divElement.className = "vditor-wysiwyg";
        divElement.innerHTML = "<pre class=\"vditor-reset\" placeholder=\"".concat(vditor.options.placeholder, "\"\n contenteditable=\"true\" spellcheck=\"false\"></pre>\n<div class=\"vditor-panel vditor-panel--none\"></div>\n<div class=\"vditor-panel vditor-panel--none\">\n    <button type=\"button\" aria-label=\"").concat(window.VditorI18n.comment, "\" class=\"vditor-icon vditor-tooltipped vditor-tooltipped__n\">\n        <svg><use xlink:href=\"#vditor-icon-comment\"></use></svg>\n    </button>\n</div>");
        this.element = divElement.firstElementChild;
        this.popover = divElement.firstElementChild.nextElementSibling;
        this.selectPopover = divElement.lastElementChild;
        this.bindEvent(vditor);
        focusEvent(vditor, this.element);
        dblclickEvent(vditor, this.element);
        blurEvent(vditor, this.element);
        hotkeyEvent(vditor, this.element);
        selectEvent(vditor, this.element);
        dropEvent(vditor, this.element);
        copyEvent(vditor, this.element, this.copy);
        cutEvent(vditor, this.element, this.copy);
        if (vditor.options.comment.enable) {
            this.selectPopover.querySelector("button").onclick = function () {
                var id = Lute.NewNodeID();
                var range = getSelection().getRangeAt(0);
                var rangeClone = range.cloneRange();
                var contents = range.extractContents();
                var blockStartElement;
                var blockEndElement;
                var removeStart = false;
                var removeEnd = false;
                contents.childNodes.forEach(function (item, index) {
                    var wrap = false;
                    if (item.nodeType === 3) {
                        wrap = true;
                    }
                    else if (!item.classList.contains("vditor-comment")) {
                        wrap = true;
                    }
                    else if (item.classList.contains("vditor-comment")) {
                        item.setAttribute("data-cmtids", item.getAttribute("data-cmtids") + " " + id);
                    }
                    if (wrap) {
                        if (item.nodeType !== 3 && item.getAttribute("data-block") === "0"
                            && index === 0 && rangeClone.startOffset > 0) {
                            item.innerHTML =
                                "<span class=\"vditor-comment\" data-cmtids=\"".concat(id, "\">").concat(item.innerHTML, "</span>");
                            blockStartElement = item;
                        }
                        else if (item.nodeType !== 3 && item.getAttribute("data-block") === "0"
                            && index === contents.childNodes.length - 1
                            && rangeClone.endOffset < rangeClone.endContainer.textContent.length) {
                            item.innerHTML =
                                "<span class=\"vditor-comment\" data-cmtids=\"".concat(id, "\">").concat(item.innerHTML, "</span>");
                            blockEndElement = item;
                        }
                        else if (item.nodeType !== 3 && item.getAttribute("data-block") === "0") {
                            if (index === 0) {
                                removeStart = true;
                            }
                            else if (index === contents.childNodes.length - 1) {
                                removeEnd = true;
                            }
                            item.innerHTML =
                                "<span class=\"vditor-comment\" data-cmtids=\"".concat(id, "\">").concat(item.innerHTML, "</span>");
                        }
                        else {
                            var commentElement = document.createElement("span");
                            commentElement.classList.add("vditor-comment");
                            commentElement.setAttribute("data-cmtids", id);
                            item.parentNode.insertBefore(commentElement, item);
                            commentElement.appendChild(item);
                        }
                    }
                });
                var startElement = (0,hasClosest/* hasClosestBlock */.F9)(rangeClone.startContainer);
                if (startElement) {
                    if (blockStartElement) {
                        startElement.insertAdjacentHTML("beforeend", blockStartElement.innerHTML);
                        blockStartElement.remove();
                    }
                    else if (startElement.textContent.trim().replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "" && removeStart) {
                        startElement.remove();
                    }
                }
                var endElement = (0,hasClosest/* hasClosestBlock */.F9)(rangeClone.endContainer);
                if (endElement) {
                    if (blockEndElement) {
                        endElement.insertAdjacentHTML("afterbegin", blockEndElement.innerHTML);
                        blockEndElement.remove();
                    }
                    else if (endElement.textContent.trim().replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "" && removeEnd) {
                        endElement.remove();
                    }
                }
                range.insertNode(contents);
                vditor.options.comment.add(id, range.toString(), _this.getComments(vditor, true));
                afterRenderEvent(vditor, {
                    enableAddUndoStack: true,
                    enableHint: false,
                    enableInput: false,
                });
                _this.hideComment();
            };
        }
    }
    WYSIWYG.prototype.getComments = function (vditor, getData) {
        var _this = this;
        if (getData === void 0) { getData = false; }
        if (vditor.currentMode === "wysiwyg" && vditor.options.comment.enable) {
            this.commentIds = [];
            this.element.querySelectorAll(".vditor-comment").forEach(function (item) {
                _this.commentIds =
                    _this.commentIds.concat(item.getAttribute("data-cmtids").split(" "));
            });
            this.commentIds = Array.from(new Set(this.commentIds));
            var comments_1 = [];
            if (getData) {
                this.commentIds.forEach(function (id) {
                    comments_1.push({
                        id: id,
                        top: _this.element.querySelector(".vditor-comment[data-cmtids=\"".concat(id, "\"]")).offsetTop,
                    });
                });
                return comments_1;
            }
        }
        else {
            return [];
        }
    };
    WYSIWYG.prototype.triggerRemoveComment = function (vditor) {
        var difference = function (a, b) {
            var s = new Set(b);
            return a.filter(function (x) { return !s.has(x); });
        };
        if (vditor.currentMode === "wysiwyg" && vditor.options.comment.enable && vditor.wysiwyg.commentIds.length > 0) {
            var oldIds = JSON.parse(JSON.stringify(this.commentIds));
            this.getComments(vditor);
            var removedIds = difference(oldIds, this.commentIds);
            if (removedIds.length > 0) {
                vditor.options.comment.remove(removedIds);
            }
        }
    };
    WYSIWYG.prototype.showComment = function () {
        var position = (0,selection/* getCursorPosition */.Ny)(this.element);
        this.selectPopover.setAttribute("style", "left:".concat(position.left, "px;display:block;top:").concat(Math.max(-8, position.top - 21), "px"));
    };
    WYSIWYG.prototype.hideComment = function () {
        this.selectPopover.setAttribute("style", "display:none");
    };
    WYSIWYG.prototype.unbindListener = function () {
        window.removeEventListener("scroll", this.scrollListener);
    };
    WYSIWYG.prototype.copy = function (event, vditor) {
        var range = getSelection().getRangeAt(0);
        if (range.toString() === "") {
            return;
        }
        event.stopPropagation();
        event.preventDefault();
        var codeElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "CODE");
        var codeEndElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.endContainer, "CODE");
        if (codeElement && codeEndElement && codeEndElement.isSameNode(codeElement)) {
            var codeText = "";
            if (codeElement.parentElement.tagName === "PRE") {
                codeText = range.toString();
            }
            else {
                codeText = "`" + range.toString() + "`";
            }
            event.clipboardData.setData("text/plain", codeText);
            event.clipboardData.setData("text/html", "");
            return;
        }
        var aElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.startContainer, "A");
        var aEndElement = (0,hasClosest/* hasClosestByMatchTag */.lG)(range.endContainer, "A");
        if (aElement && aEndElement && aEndElement.isSameNode(aElement)) {
            var aTitle = aElement.getAttribute("title") || "";
            if (aTitle) {
                aTitle = " \"".concat(aTitle, "\"");
            }
            event.clipboardData.setData("text/plain", "[".concat(range.toString(), "](").concat(aElement.getAttribute("href")).concat(aTitle, ")"));
            event.clipboardData.setData("text/html", "");
            return;
        }
        var tempElement = document.createElement("div");
        tempElement.appendChild(range.cloneContents());
        event.clipboardData.setData("text/plain", vditor.lute.VditorDOM2Md(tempElement.innerHTML).trim());
        event.clipboardData.setData("text/html", "");
    };
    WYSIWYG.prototype.bindEvent = function (vditor) {
        var _this = this;
        this.unbindListener();
        window.addEventListener("scroll", this.scrollListener = function () {
            hidePanel(vditor, ["hint"]);
            if (_this.popover.style.display !== "block" || _this.selectPopover.style.display !== "block") {
                return;
            }
            var top = parseInt(_this.popover.getAttribute("data-top"), 10);
            if (vditor.options.height !== "auto") {
                if (vditor.options.toolbarConfig.pin && vditor.toolbar.element.getBoundingClientRect().top === 0) {
                    var popoverTop = Math.max(window.scrollY - vditor.element.offsetTop - 8, Math.min(top - vditor.wysiwyg.element.scrollTop, _this.element.clientHeight - 21)) + "px";
                    if (_this.popover.style.display === "block") {
                        _this.popover.style.top = popoverTop;
                    }
                    if (_this.selectPopover.style.display === "block") {
                        _this.selectPopover.style.top = popoverTop;
                    }
                }
                return;
            }
            else if (!vditor.options.toolbarConfig.pin) {
                return;
            }
            var popoverTop1 = Math.max(top, (window.scrollY - vditor.element.offsetTop - 8)) + "px";
            if (_this.popover.style.display === "block") {
                _this.popover.style.top = popoverTop1;
            }
            if (_this.selectPopover.style.display === "block") {
                _this.selectPopover.style.top = popoverTop1;
            }
        });
        this.element.addEventListener("scroll", function () {
            hidePanel(vditor, ["hint"]);
            if (vditor.options.comment && vditor.options.comment.enable && vditor.options.comment.scroll) {
                vditor.options.comment.scroll(vditor.wysiwyg.element.scrollTop);
            }
            if (_this.popover.style.display !== "block") {
                return;
            }
            var top = parseInt(_this.popover.getAttribute("data-top"), 10) - vditor.wysiwyg.element.scrollTop;
            var max = -8;
            if (vditor.options.toolbarConfig.pin && vditor.toolbar.element.getBoundingClientRect().top === 0) {
                max = window.scrollY - vditor.element.offsetTop + max;
            }
            var topPx = Math.max(max, Math.min(top, _this.element.clientHeight - 21)) + "px";
            _this.popover.style.top = topPx;
            _this.selectPopover.style.top = topPx;
        });
        this.element.addEventListener("paste", function (event) {
            paste(vditor, event, {
                pasteCode: function (code) {
                    var range = (0,selection/* getEditorRange */.zh)(vditor);
                    var node = document.createElement("template");
                    node.innerHTML = code;
                    range.insertNode(node.content.cloneNode(true));
                    var blockElement = (0,hasClosest/* hasClosestByAttribute */.a1)(range.startContainer, "data-block", "0");
                    if (blockElement) {
                        blockElement.outerHTML = vditor.lute.SpinVditorDOM(blockElement.outerHTML);
                    }
                    else {
                        vditor.wysiwyg.element.innerHTML = vditor.lute.SpinVditorDOM(vditor.wysiwyg.element.innerHTML);
                    }
                    (0,selection/* setRangeByWbr */.ib)(vditor.wysiwyg.element, range);
                },
            });
        });
        // 中文处理
        this.element.addEventListener("compositionstart", function () {
            _this.composingLock = true;
        });
        this.element.addEventListener("compositionend", function (event) {
            var headingElement = (0,hasClosestByHeadings/* hasClosestByHeadings */.W)(getSelection().getRangeAt(0).startContainer);
            if (headingElement && headingElement.textContent === "") {
                // heading 为空删除 https://github.com/Vanessa219/vditor/issues/150
                renderToc(vditor);
                return;
            }
            if (!(0,compatibility/* isFirefox */.vU)()) {
                input_input(vditor, getSelection().getRangeAt(0).cloneRange(), event);
            }
            _this.composingLock = false;
        });
        this.element.addEventListener("input", function (event) {
            if (event.inputType === "deleteByDrag" || event.inputType === "insertFromDrop") {
                // https://github.com/Vanessa219/vditor/issues/801 编辑器内容拖拽问题
                return;
            }
            if (_this.preventInput) {
                _this.preventInput = false;
                afterRenderEvent(vditor);
                return;
            }
            if (_this.composingLock || event.data === "‘" || event.data === "“" || event.data === "《") {
                afterRenderEvent(vditor);
                return;
            }
            var range = getSelection().getRangeAt(0);
            var blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
            if (!blockElement) {
                // 没有被块元素包裹
                modifyPre(vditor, range);
                blockElement = (0,hasClosest/* hasClosestBlock */.F9)(range.startContainer);
            }
            if (!blockElement) {
                return;
            }
            // 前后空格处理
            var startOffset = (0,selection/* getSelectPosition */.im)(blockElement, vditor.wysiwyg.element, range).start;
            // 开始可以输入空格
            var startSpace = true;
            for (var i = startOffset - 1; i > blockElement.textContent.substr(0, startOffset).lastIndexOf("\n"); i--) {
                if (blockElement.textContent.charAt(i) !== " " &&
                    // 多个 tab 前删除不形成代码块 https://github.com/Vanessa219/vditor/issues/162 1
                    blockElement.textContent.charAt(i) !== "\t") {
                    startSpace = false;
                    break;
                }
            }
            if (startOffset === 0) {
                startSpace = false;
            }
            // 结尾可以输入空格
            var endSpace = true;
            for (var i = startOffset - 1; i < blockElement.textContent.length; i++) {
                if (blockElement.textContent.charAt(i) !== " " && blockElement.textContent.charAt(i) !== "\n") {
                    endSpace = false;
                    break;
                }
            }
            var headingElement = (0,hasClosestByHeadings/* hasClosestByHeadings */.W)(getSelection().getRangeAt(0).startContainer);
            if (headingElement && headingElement.textContent === "") {
                // heading 为空删除 https://github.com/Vanessa219/vditor/issues/150
                renderToc(vditor);
                headingElement.remove();
            }
            if ((startSpace && blockElement.getAttribute("data-type") !== "code-block")
                || endSpace || isHeadingMD(blockElement.innerHTML) ||
                (isHrMD(blockElement.innerHTML) && blockElement.previousElementSibling)) {
                if (typeof vditor.options.input === "function") {
                    vditor.options.input(getMarkdown(vditor));
                }
                return;
            }
            // https://github.com/Vanessa219/vditor/issues/1565
            if (event.inputType === "insertParagraph" && _this.element.innerHTML === '<p><br></p><p><br></p>') {
                blockElement.previousElementSibling.remove();
            }
            input_input(vditor, range, event);
        });
        this.element.addEventListener("click", function (event) {
            if (event.target.tagName === "INPUT") {
                var checkElement = event.target;
                if (checkElement.checked) {
                    checkElement.setAttribute("checked", "checked");
                }
                else {
                    checkElement.removeAttribute("checked");
                }
                _this.preventInput = true;
                afterRenderEvent(vditor);
                return;
            }
            if (event.target.tagName === "IMG" &&
                // plantuml 图片渲染不进行提示
                !event.target.parentElement.classList.contains("vditor-wysiwyg__preview")) {
                if (event.target.getAttribute("data-type") === "link-ref") {
                    genLinkRefPopover(vditor, event.target);
                }
                else {
                    genImagePopover(event, vditor);
                }
                return;
            }
            // 打开链接
            var a = (0,hasClosest/* hasClosestByMatchTag */.lG)(event.target, "A");
            if (a) {
                if (vditor.options.link.click) {
                    vditor.options.link.click(a);
                }
                else if (vditor.options.link.isOpen) {
                    window.open(a.getAttribute("href"));
                }
                event.preventDefault();
                return;
            }
            var range = (0,selection/* getEditorRange */.zh)(vditor);
            if (event.target.isEqualNode(_this.element) && _this.element.lastElementChild && range.collapsed) {
                var lastRect = _this.element.lastElementChild.getBoundingClientRect();
                if (event.y > lastRect.top + lastRect.height) {
                    if (_this.element.lastElementChild.tagName === "P" &&
                        _this.element.lastElementChild.textContent.trim().replace(constants/* Constants.ZWSP */.g.ZWSP, "") === "") {
                        range.selectNodeContents(_this.element.lastElementChild);
                        range.collapse(false);
                    }
                    else {
                        _this.element.insertAdjacentHTML("beforeend", "<p data-block=\"0\">".concat(constants/* Constants.ZWSP */.g.ZWSP, "<wbr></p>"));
                        (0,selection/* setRangeByWbr */.ib)(_this.element, range);
                    }
                }
            }
            highlightToolbarWYSIWYG(vditor);
            // 点击后光标落于预览区，需展开代码块
            var previewElement = (0,hasClosest/* hasClosestByClassName */.fb)(event.target, "vditor-wysiwyg__preview");
            if (!previewElement) {
                previewElement =
                    (0,hasClosest/* hasClosestByClassName */.fb)((0,selection/* getEditorRange */.zh)(vditor).startContainer, "vditor-wysiwyg__preview");
            }
            if (previewElement) {
                showCode(previewElement, vditor);
            }
            clickToc(event, vditor);
        });
        this.element.addEventListener("keyup", function (event) {
            if (event.isComposing || (0,compatibility/* isCtrl */.yl)(event)) {
                return;
            }
            // 除 md 处理、cell 内换行、table 添加新行/列、代码块语言切换、block render 换行、跳出/逐层跳出 blockquote、h6 换行、
            // 任务列表换行、软换行外需在换行时调整文档位置
            if (event.key === "Enter") {
                scrollCenter(vditor);
            }
            if ((event.key === "Backspace" || event.key === "Delete") &&
                vditor.wysiwyg.element.innerHTML !== "" && vditor.wysiwyg.element.childNodes.length === 1 &&
                vditor.wysiwyg.element.firstElementChild && vditor.wysiwyg.element.firstElementChild.tagName === "P"
                && vditor.wysiwyg.element.firstElementChild.childElementCount === 0
                && (vditor.wysiwyg.element.textContent === "" || vditor.wysiwyg.element.textContent === "\n")) {
                // 为空时显示 placeholder
                vditor.wysiwyg.element.innerHTML = "";
            }
            var range = (0,selection/* getEditorRange */.zh)(vditor);
            if (event.key === "Backspace") {
                // firefox headings https://github.com/Vanessa219/vditor/issues/211
                if ((0,compatibility/* isFirefox */.vU)() && range.startContainer.textContent === "\n" && range.startOffset === 1) {
                    range.startContainer.textContent = "";
                }
            }
            // 没有被块元素包裹
            modifyPre(vditor, range);
            highlightToolbarWYSIWYG(vditor);
            if (event.key !== "ArrowDown" && event.key !== "ArrowRight" && event.key !== "Backspace"
                && event.key !== "ArrowLeft" && event.key !== "ArrowUp") {
                return;
            }
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                vditor.hint.render(vditor);
            }
            // 上下左右，删除遇到块预览的处理
            var previewElement = (0,hasClosest/* hasClosestByClassName */.fb)(range.startContainer, "vditor-wysiwyg__preview");
            if (!previewElement && range.startContainer.nodeType !== 3 && range.startOffset > 0) {
                // table 前删除遇到代码块
                var blockRenderElement = range.startContainer;
                if (blockRenderElement.classList.contains("vditor-wysiwyg__block")) {
                    previewElement = blockRenderElement.lastElementChild;
                }
            }
            if (!previewElement) {
                return;
            }
            var previousElement = previewElement.previousElementSibling;
            if (previousElement.style.display === "none") {
                if (event.key === "ArrowDown" || event.key === "ArrowRight") {
                    showCode(previewElement, vditor);
                }
                else {
                    showCode(previewElement, vditor, false);
                }
                return;
            }
            var codeElement = previewElement.previousElementSibling;
            if (codeElement.tagName === "PRE") {
                codeElement = codeElement.firstElementChild;
            }
            if (event.key === "ArrowDown" || event.key === "ArrowRight") {
                var blockRenderElement = previewElement.parentElement;
                var nextNode = getRenderElementNextNode(blockRenderElement);
                if (nextNode && nextNode.nodeType !== 3) {
                    // 下一节点依旧为代码渲染块
                    var nextRenderElement = nextNode.querySelector(".vditor-wysiwyg__preview");
                    if (nextRenderElement) {
                        showCode(nextRenderElement, vditor);
                        return;
                    }
                }
                // 跳过渲染块，光标移动到下一个节点
                if (nextNode.nodeType === 3) {
                    // inline
                    while (nextNode.textContent.length === 0 && nextNode.nextSibling) {
                        // https://github.com/Vanessa219/vditor/issues/100 2
                        nextNode = nextNode.nextSibling;
                    }
                    range.setStart(nextNode, 1);
                }
                else {
                    // block
                    range.setStart(nextNode.firstChild, 0);
                }
            }
            else {
                range.selectNodeContents(codeElement);
                range.collapse(false);
            }
        });
    };
    return WYSIWYG;
}());


;// CONCATENATED MODULE: ./src/index.ts
var src_extends = (undefined && undefined.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();





































var Vditor = /** @class */ (function (_super) {
    src_extends(Vditor, _super);
    /**
     * @param id 要挂载 Vditor 的元素或者元素 ID。
     * @param options Vditor 参数
     */
    function Vditor(id, options) {
        var _this = _super.call(this) || this;
        _this.version = constants/* VDITOR_VERSION */.H;
        if (typeof id === "string") {
            if (!options) {
                options = {
                    cache: {
                        id: "vditor".concat(id),
                    },
                };
            }
            else if (!options.cache) {
                options.cache = { id: "vditor".concat(id) };
            }
            else if (!options.cache.id) {
                options.cache.id = "vditor".concat(id);
            }
            if (!document.getElementById(id)) {
                _this.showErrorTip("Failed to get element by id: ".concat(id));
                return _this;
            }
            id = document.getElementById(id);
        }
        var getOptions = new Options(options);
        var mergedOptions = getOptions.merge();
        // 支持自定义国际化
        if (!mergedOptions.i18n) {
            if (!["en_US", "fr_FR", "pt_BR", "ja_JP", "ko_KR", "ru_RU", "sv_SE", "zh_CN", "zh_TW"].includes(mergedOptions.lang)) {
                throw new Error("options.lang error, see https://ld246.com/article/1549638745630#options");
            }
            else {
                var i18nScriptPrefix = "vditorI18nScript";
                var i18nScriptID_1 = i18nScriptPrefix + mergedOptions.lang;
                document.querySelectorAll("head script[id^=\"".concat(i18nScriptPrefix, "\"]")).forEach(function (el) {
                    if (el.id !== i18nScriptID_1) {
                        document.head.removeChild(el);
                    }
                });
                (0,addScript/* addScript */.G)("".concat(mergedOptions.cdn, "/dist/js/i18n/").concat(mergedOptions.lang, ".js"), i18nScriptID_1).then(function () {
                    _this.init(id, mergedOptions);
                }).catch(function (error) {
                    _this.showErrorTip("GET ".concat(mergedOptions.cdn, "/dist/js/i18n/").concat(mergedOptions.lang, ".js net::ERR_ABORTED 404 (Not Found)"));
                });
            }
        }
        else {
            window.VditorI18n = mergedOptions.i18n;
            _this.init(id, mergedOptions);
        }
        return _this;
    }
    Vditor.prototype.showErrorTip = function (error) {
        var tip = new Tip();
        document.body.appendChild(tip.element);
        tip.show(error, 0);
    };
    Vditor.prototype.updateToolbarConfig = function (options) {
        this.vditor.toolbar.updateConfig(this.vditor, options);
    };
    /** 设置主题 */
    Vditor.prototype.setTheme = function (theme, contentTheme, codeTheme, contentThemePath) {
        this.vditor.options.theme = theme;
        setTheme(this.vditor);
        if (contentTheme) {
            this.vditor.options.preview.theme.current = contentTheme;
            (0,setContentTheme/* setContentTheme */.Z)(contentTheme, contentThemePath || this.vditor.options.preview.theme.path);
        }
        if (codeTheme) {
            this.vditor.options.preview.hljs.style = codeTheme;
            (0,setCodeTheme/* setCodeTheme */.Y)(codeTheme, this.vditor.options.cdn);
        }
    };
    /** 获取 Markdown 内容 */
    Vditor.prototype.getValue = function () {
        return getMarkdown(this.vditor);
    };
    /** 获取编辑器当前编辑模式 */
    Vditor.prototype.getCurrentMode = function () {
        return this.vditor.currentMode;
    };
    /** 聚焦到编辑器 */
    Vditor.prototype.focus = function () {
        if (this.vditor.currentMode === "sv") {
            this.vditor.sv.element.focus();
        }
        else if (this.vditor.currentMode === "wysiwyg") {
            this.vditor.wysiwyg.element.focus();
        }
        else if (this.vditor.currentMode === "ir") {
            this.vditor.ir.element.focus();
        }
    };
    /** 让编辑器失焦 */
    Vditor.prototype.blur = function () {
        if (this.vditor.currentMode === "sv") {
            this.vditor.sv.element.blur();
        }
        else if (this.vditor.currentMode === "wysiwyg") {
            this.vditor.wysiwyg.element.blur();
        }
        else if (this.vditor.currentMode === "ir") {
            this.vditor.ir.element.blur();
        }
    };
    /** 禁用编辑器 */
    Vditor.prototype.disabled = function () {
        hidePanel(this.vditor, ["subToolbar", "hint", "popover"]);
        disableToolbar(this.vditor.toolbar.elements, constants/* Constants.EDIT_TOOLBARS.concat */.g.EDIT_TOOLBARS.concat(["undo", "redo", "fullscreen", "edit-mode"]));
        this.vditor[this.vditor.currentMode].element.setAttribute("contenteditable", "false");
    };
    /** 解除编辑器禁用 */
    Vditor.prototype.enable = function () {
        enableToolbar(this.vditor.toolbar.elements, constants/* Constants.EDIT_TOOLBARS.concat */.g.EDIT_TOOLBARS.concat(["undo", "redo", "fullscreen", "edit-mode"]));
        this.vditor.undo.resetIcon(this.vditor);
        this.vditor[this.vditor.currentMode].element.setAttribute("contenteditable", "true");
    };
    /** 返回选中的字符串 */
    Vditor.prototype.getSelection = function () {
        if (this.vditor.currentMode === "wysiwyg") {
            return getSelectText(this.vditor.wysiwyg.element);
        }
        else if (this.vditor.currentMode === "sv") {
            return getSelectText(this.vditor.sv.element);
        }
        else if (this.vditor.currentMode === "ir") {
            return getSelectText(this.vditor.ir.element);
        }
    };
    /** 设置预览区域内容 */
    Vditor.prototype.renderPreview = function (value) {
        this.vditor.preview.render(this.vditor, value);
    };
    /** 获取焦点位置 */
    Vditor.prototype.getCursorPosition = function () {
        return (0,selection/* getCursorPosition */.Ny)(this.vditor[this.vditor.currentMode].element);
    };
    /** 上传是否还在进行中 */
    Vditor.prototype.isUploading = function () {
        return this.vditor.upload.isUploading;
    };
    /** 清除缓存 */
    Vditor.prototype.clearCache = function () {
        localStorage.removeItem(this.vditor.options.cache.id);
    };
    /** 禁用缓存 */
    Vditor.prototype.disabledCache = function () {
        this.vditor.options.cache.enable = false;
    };
    /** 启用缓存 */
    Vditor.prototype.enableCache = function () {
        if (!this.vditor.options.cache.id) {
            throw new Error("need options.cache.id, see https://ld246.com/article/1549638745630#options");
        }
        this.vditor.options.cache.enable = true;
    };
    /** HTML 转 md */
    Vditor.prototype.html2md = function (value) {
        return this.vditor.lute.HTML2Md(value);
    };
    /** markdown 转 JSON 输出 */
    Vditor.prototype.exportJSON = function (value) {
        return this.vditor.lute.RenderJSON(value);
    };
    /** 获取 HTML */
    Vditor.prototype.getHTML = function () {
        return getHTML(this.vditor);
    };
    /** 消息提示。time 为 0 将一直显示 */
    Vditor.prototype.tip = function (text, time) {
        this.vditor.tip.show(text, time);
    };
    /** 设置预览模式 */
    Vditor.prototype.setPreviewMode = function (mode) {
        setPreviewMode(mode, this.vditor);
    };
    /** 删除选中内容 */
    Vditor.prototype.deleteValue = function () {
        if (window.getSelection().isCollapsed) {
            return;
        }
        document.execCommand("delete", false);
    };
    /** 更新选中内容 */
    Vditor.prototype.updateValue = function (value) {
        document.execCommand("insertHTML", false, value);
    };
    /** 在焦点处插入内容，并默认进行 Markdown 渲染 */
    Vditor.prototype.insertValue = function (value, render) {
        if (render === void 0) { render = true; }
        var range = (0,selection/* getEditorRange */.zh)(this.vditor);
        range.collapse(true);
        var tmpElement = document.createElement("template");
        tmpElement.innerHTML = value;
        range.insertNode(tmpElement.content.cloneNode(true));
        range.collapse(false);
        if (this.vditor.currentMode === "sv") {
            this.vditor.sv.preventInput = true;
            if (render) {
                inputEvent(this.vditor);
            }
        }
        else if (this.vditor.currentMode === "wysiwyg") {
            // 由于 https://github.com/Vanessa219/vditor/issues/1566 不能使用 this.vditor.wysiwyg.preventInput = true;
            if (render) {
                input_input(this.vditor, getSelection().getRangeAt(0));
            }
        }
        else if (this.vditor.currentMode === "ir") {
            this.vditor.ir.preventInput = true;
            if (render) {
                input(this.vditor, getSelection().getRangeAt(0), true);
            }
        }
    };
    /** 设置编辑器内容 */
    Vditor.prototype.setValue = function (markdown, clearStack) {
        var _this = this;
        if (clearStack === void 0) { clearStack = false; }
        if (this.vditor.currentMode === "sv") {
            this.vditor.sv.element.innerHTML = "<div data-block='0'>".concat(this.vditor.lute.SpinVditorSVDOM(markdown), "</div>");
            processAfterRender(this.vditor, {
                enableAddUndoStack: true,
                enableHint: false,
                enableInput: false,
            });
        }
        else if (this.vditor.currentMode === "wysiwyg") {
            renderDomByMd(this.vditor, markdown, {
                enableAddUndoStack: true,
                enableHint: false,
                enableInput: false,
            });
        }
        else {
            this.vditor.ir.element.innerHTML = this.vditor.lute.Md2VditorIRDOM(markdown);
            this.vditor.ir.element
                .querySelectorAll(".vditor-ir__preview[data-render='2']")
                .forEach(function (item) {
                processCodeRender(item, _this.vditor);
            });
            process_processAfterRender(this.vditor, {
                enableAddUndoStack: true,
                enableHint: false,
                enableInput: false,
            });
        }
        this.vditor.outline.render(this.vditor);
        if (!markdown) {
            hidePanel(this.vditor, ["emoji", "headings", "submenu", "hint"]);
            if (this.vditor.wysiwyg.popover) {
                this.vditor.wysiwyg.popover.style.display = "none";
            }
            this.clearCache();
        }
        if (clearStack) {
            this.clearStack();
        }
    };
    /** 清空 undo & redo 栈 */
    Vditor.prototype.clearStack = function () {
        this.vditor.undo.clearStack(this.vditor);
        this.vditor.undo.addToUndoStack(this.vditor);
    };
    /** 销毁编辑器 */
    Vditor.prototype.destroy = function () {
        this.vditor.element.innerHTML = this.vditor.originalInnerHTML;
        this.vditor.element.classList.remove("vditor");
        this.vditor.element.removeAttribute("style");
        var iconScript = document.getElementById("vditorIconScript");
        if (iconScript) {
            iconScript.remove();
        }
        this.clearCache();
        UIUnbindListener();
        this.vditor.wysiwyg.unbindListener();
    };
    /** 获取评论 ID */
    Vditor.prototype.getCommentIds = function () {
        if (this.vditor.currentMode !== "wysiwyg") {
            return [];
        }
        return this.vditor.wysiwyg.getComments(this.vditor, true);
    };
    /** 高亮评论 */
    Vditor.prototype.hlCommentIds = function (ids) {
        if (this.vditor.currentMode !== "wysiwyg") {
            return;
        }
        var hlItem = function (item) {
            item.classList.remove("vditor-comment--hover");
            ids.forEach(function (id) {
                if (item.getAttribute("data-cmtids").indexOf(id) > -1) {
                    item.classList.add("vditor-comment--hover");
                }
            });
        };
        this.vditor.wysiwyg.element
            .querySelectorAll(".vditor-comment")
            .forEach(function (item) {
            hlItem(item);
        });
        if (this.vditor.preview.element.style.display !== "none") {
            this.vditor.preview.element
                .querySelectorAll(".vditor-comment")
                .forEach(function (item) {
                hlItem(item);
            });
        }
    };
    /** 取消评论高亮 */
    Vditor.prototype.unHlCommentIds = function (ids) {
        if (this.vditor.currentMode !== "wysiwyg") {
            return;
        }
        var unHlItem = function (item) {
            ids.forEach(function (id) {
                if (item.getAttribute("data-cmtids").indexOf(id) > -1) {
                    item.classList.remove("vditor-comment--hover");
                }
            });
        };
        this.vditor.wysiwyg.element
            .querySelectorAll(".vditor-comment")
            .forEach(function (item) {
            unHlItem(item);
        });
        if (this.vditor.preview.element.style.display !== "none") {
            this.vditor.preview.element
                .querySelectorAll(".vditor-comment")
                .forEach(function (item) {
                unHlItem(item);
            });
        }
    };
    /** 删除评论 */
    Vditor.prototype.removeCommentIds = function (removeIds) {
        var _this = this;
        if (this.vditor.currentMode !== "wysiwyg") {
            return;
        }
        var removeItem = function (item, removeId) {
            var ids = item.getAttribute("data-cmtids").split(" ");
            ids.find(function (id, index) {
                if (id === removeId) {
                    ids.splice(index, 1);
                    return true;
                }
            });
            if (ids.length === 0) {
                item.outerHTML = item.innerHTML;
                (0,selection/* getEditorRange */.zh)(_this.vditor).collapse(true);
            }
            else {
                item.setAttribute("data-cmtids", ids.join(" "));
            }
        };
        removeIds.forEach(function (removeId) {
            _this.vditor.wysiwyg.element
                .querySelectorAll(".vditor-comment")
                .forEach(function (item) {
                removeItem(item, removeId);
            });
            if (_this.vditor.preview.element.style.display !== "none") {
                _this.vditor.preview.element
                    .querySelectorAll(".vditor-comment")
                    .forEach(function (item) {
                    removeItem(item, removeId);
                });
            }
        });
        afterRenderEvent(this.vditor, {
            enableAddUndoStack: true,
            enableHint: false,
            enableInput: false,
        });
    };
    Vditor.prototype.init = function (id, mergedOptions) {
        var _this = this;
        this.vditor = {
            currentMode: mergedOptions.mode,
            element: id,
            hint: new Hint(mergedOptions.hint.extend),
            lute: undefined,
            options: mergedOptions,
            originalInnerHTML: id.innerHTML,
            outline: new Outline(window.VditorI18n.outline),
            tip: new Tip(),
        };
        this.vditor.sv = new Editor(this.vditor);
        this.vditor.undo = new undo_Undo();
        this.vditor.wysiwyg = new WYSIWYG(this.vditor);
        this.vditor.ir = new IR(this.vditor);
        this.vditor.toolbar = new Toolbar(this.vditor);
        if (mergedOptions.resize.enable) {
            this.vditor.resize = new Resize(this.vditor);
        }
        if (this.vditor.toolbar.elements.devtools) {
            this.vditor.devtools = new DevTools();
        }
        if (mergedOptions.upload.url || mergedOptions.upload.handler) {
            this.vditor.upload = new Upload();
        }
        (0,addScript/* addScript */.G)(mergedOptions._lutePath ||
            "".concat(mergedOptions.cdn, "/dist/js/lute/lute.min.js"), "vditorLuteScript").then(function () {
            _this.vditor.lute = (0,setLute/* setLute */.X)({
                autoSpace: _this.vditor.options.preview.markdown.autoSpace,
                gfmAutoLink: _this.vditor.options.preview.markdown.gfmAutoLink,
                codeBlockPreview: _this.vditor.options.preview.markdown
                    .codeBlockPreview,
                emojiSite: _this.vditor.options.hint.emojiPath,
                emojis: _this.vditor.options.hint.emoji,
                fixTermTypo: _this.vditor.options.preview.markdown.fixTermTypo,
                footnotes: _this.vditor.options.preview.markdown.footnotes,
                headingAnchor: false,
                inlineMathDigit: _this.vditor.options.preview.math.inlineDigit,
                linkBase: _this.vditor.options.preview.markdown.linkBase,
                linkPrefix: _this.vditor.options.preview.markdown.linkPrefix,
                listStyle: _this.vditor.options.preview.markdown.listStyle,
                mark: _this.vditor.options.preview.markdown.mark,
                mathBlockPreview: _this.vditor.options.preview.markdown
                    .mathBlockPreview,
                paragraphBeginningSpace: _this.vditor.options.preview.markdown
                    .paragraphBeginningSpace,
                sanitize: _this.vditor.options.preview.markdown.sanitize,
                toc: _this.vditor.options.preview.markdown.toc,
            });
            _this.vditor.preview = new Preview(_this.vditor);
            initUI(_this.vditor);
            if (mergedOptions.after) {
                mergedOptions.after();
            }
            if (mergedOptions.icon) {
                // 防止初始化 2 个编辑器时加载 2 次
                (0,addScript/* addScriptSync */.J)("".concat(mergedOptions.cdn, "/dist/js/icons/").concat(mergedOptions.icon, ".js"), "vditorIconScript");
            }
        });
    };
    return Vditor;
}(method["default"]));
/* harmony default export */ const src = (Vditor);

})();

__webpack_exports__ = __webpack_exports__["default"];
/******/ 	return __webpack_exports__;
/******/ })()
;
});