(function (window, undefined) {
  let selectText = ''

  window.Asc.plugin.init = function (e) {
    selectText = e
  }
  window.Asc.plugin.event_onClick = function () {
    selectText = ''
  }

  window.Asc.plugin.button = function (id) {
  }

  const EventMap = {
    sendToParent (method, data) {
      let params = {
        type: 'onExternalFrameMessage',
        method,
        data
      }
      window.top.postMessage(JSON.stringify(params), location.origin)
    },
    focusInDocument (data) {
      window.Asc.scope.field = {
        id: data.id,
        fieldFlag: data.fieldFlag,
        $index: data.$index || 1
      }
      window.Asc.plugin.callCommand(function () {
        let field = Asc.scope.field || {}
        let index = field.$index ? field.$index : 1
        let oDoc = Api.GetDocument()
        let flag = `{{${field.fieldFlag}}}`
        let oRange = oDoc.Search(flag)
        let cur = 1
        for (let i = 0; i < oRange.length; i++) {
          if (oRange[i].GetText() === flag) {
            if (cur === index) {
              oRange[i].Select()
              break
            }
            cur = cur + 1
          }
        }
      })
    },
    focusTableInDoc (data) {
      window.Asc.scope.marker = data.marker
      window.Asc.plugin.callCommand(function () {
        let flag = Asc.scope.marker || ''
        let oDoc = Api.GetDocument()
        let oRange = oDoc.GetBookmarkRange(flag)
        oRange.Select()
      })
    },
    addMarker (data) {
      let flag = '{{' + data.fieldFlag + '}}'
      window.Asc.plugin.executeMethod('PasteText', [flag])
    },
    addBookMarker (data) {
      window.Asc.scope.value = data
      window.Asc.plugin.callCommand(function () {
        let oDoc = Api.GetDocument()
        let range = oDoc.GetRangeBySelect()
        let params = {
          type: 'onExternalFrameMessage',
          method: 'addBookMarker'
        }
        let marker = Asc.scope.value
        let markers = []
        if (range) {
          let texts = range.GetText()
          let pars = range.GetAllParagraphs() || []
          let txtList = []
          for (let i = 0; i < pars.length; i++) {
              let text = pars[i].GetText()
              txtList.push(text)
          }
          let table = pars[0] ? pars[0].GetParentTable() : null
          let count = table ? table.GetRowsCount() : 0
          for (let i = 0; i < count; i++) {
            let row = table.GetRow(i)
            let firstCell = row.GetCell(0)
            let cellText = firstCell ? firstCell.GetContent().GetElement(0).GetText() : ''
            // 序号
            let isNumbering = false
            if (firstCell.GetContent().GetElement(0).GetNumbering()) {
              isNumbering = true
              let cellCount = row.GetCellsCount()
              for (let j = 1; j < cellCount; j++) {
                let cellItem = row.GetCell(j)
                if (!cellItem.GetContent().GetElement(0).GetNumbering()) {
                  cellText = cellItem.GetContent().GetElement(0).GetText()
                  firstCell = cellItem
                  break
                }
              }
            }
            if (cellText && txtList.includes(cellText)) {
              let cRange = firstCell.Search(cellText)[0]
              cRange.AddBookmark(marker.key + i)
              markers.push(marker.key + i)
            }
          }
          // range.AddBookmark(Asc.scope.value.key)
          params.data = Object.assign(marker, {
            key: markers.join(','),
            texts
          })
        } else {
          params.data = false
        }
        window.top.postMessage(JSON.stringify(params), location.origin)
      })
    },
    deleteBookMarker (data) {
      window.Asc.scope.value = data
      window.Asc.plugin.callCommand(function () {
        let oDoc = Api.GetDocument()
        let markers = Asc.scope.value || []
        for (let i = 0; i < markers.length; i++) {
          oDoc.DeleteBookmark(markers[i])
        }
      })
    },
    // 批量删除循环应用内标签
    deleteLoopApp (list) {
      window.Asc.scope.value = list
      window.Asc.plugin.callCommand(function () {
        let list = window.Asc.scope.value || []
        let oDoc = Api.GetDocument()
        list.forEach(row => {
          if (row.loopType === 0) {
            oDoc.SearchAndReplace({ searchString: `{{${row.startTag}}}`, replaceString: '' }, `{{${row.startTag}}}`, '')
            oDoc.SearchAndReplace({ searchString: `{{${row.endTag}}}`, replaceString: '' }, `{{${row.endTag}}}`, '')
          } else if (row.loopType === 1) {
            oDoc.DeleteBookmark(row.bookmark)
          }
        })
      })
    },
    // 更新占位符
    replaceMarker (data) {
      window.Asc.scope.st = '{{' + data.newValue + '}}'
      // 原来的值
      if (data.oldValue) {
        window.Asc.scope.old = '{{' + data.oldValue + '}}'
      } else {
        this.addMarker(data)
        return
      }
      window.Asc.plugin.callCommand(function () {
        let oDocument  = Api.GetDocument()
        oDocument.SearchAndReplace({ searchString: Asc.scope.old, replaceString: Asc.scope.st }, Asc.scope.old, Asc.scope.st)
      }, false)
    },
    // 查找并插入占位符
    findAndInsertMarker (data) {
      window.Asc.scope.st = '{{' + data.fieldName + '}}'
      window.Asc.scope.searchStr = data.fieldValue
      window.Asc.plugin.callCommand(function () {
        let oDocument = Api.GetDocument()
        oDocument.SearchAndReplace({ searchString: Asc.scope.searchStr, replaceString: Asc.scope.st }, Asc.scope.searchStr, Asc.scope.st)
      }, false)
    },
    insertPosition (data) {
      if (!selectText) {
        let postData = {
          text: selectText,
          ...data,
          selected: false
        }
        this.sendToParent('addRange', postData)
        return false
      }
      window.Asc.scope.postData = data
      window.Asc.plugin.callCommand(function() {
        let postData = Asc.scope.postData || {}
        let oDoc = Api.GetDocument()
        let oRange = oDoc.GetRangeBySelect()
        let selectText = oRange.GetText()
        let oAllPar = oRange.GetAllParagraphs()
        let oPar = oAllPar[oAllPar.length - 1]
        let parText = oPar.GetText()
        if (oAllPar.length > 1) {
          oRange.AddText(`{{${postData.start}}}`, 'before')
          if (selectText.includes(parText)) {
            let newRange = oPar.GetRange(0, parText.length - 1)
            newRange.AddText(`{{${postData.end}}}`, 'after')
          } else {
            oRange.AddText(`{{${postData.end}}}`, 'after')
          }
        } else {
          let isEnd = parText.substr(0 - selectText.length) === selectText
          isEnd = isEnd || selectText.includes(parText)
          console.log('end = ', isEnd)
          let start = Math.max(parText.indexOf(selectText), 0)
          let end = start + Math.min(parText.length, selectText.length) - 1
          let newRange = oPar.GetRange(start, end)
          oRange.AddText(`{{${postData.start}}}`, 'before')
          newRange.AddText(`{{${postData.end}}}`, 'after')
        }

        postData.selected = true
        postData.text = selectText
        let params = {
          type: 'onExternalFrameMessage',
          method: 'addRange',
          data: postData
        }
        window.top.postMessage(JSON.stringify(params), location.origin)
      })
    },
    deletePosition (data) {
      window.Asc.scope.range = data
      window.Asc.plugin.callCommand(function () {
        let oDocument  = Api.GetDocument()
        let { start, end } = Asc.scope.range
        let markers = [`{{${start}}}`, `{{${end}}}`]
        for (let j = 0; j < markers.length; j++) {
          oDocument.SearchAndReplace({ searchString: markers[j], replaceString: '' }, markers[j], '')
        }
      })
    },
    deletePositionMarker (data) {
      window.Asc.scope.data = data
      window.Asc.plugin.callCommand(function () {
        let oDocument = Api.GetDocument()
        let markers = Asc.scope.data || []
        for (let j = 0; j < markers.length; j++) {
          oDocument.SearchAndReplace({ searchString: markers[j], replaceString: '' }, markers[j], '')
        }
      })
    },
    deletePositionArray (data) {
      window.Asc.scope.data = data
      window.Asc.plugin.callCommand(function () {
        let oDocument = Api.GetDocument()
        let markers = Asc.scope.data || []
        for (let j = 0; j < markers.length; j++) {
          oDocument.SearchAndReplace({ searchString: markers[j], replaceString: '' }, markers[j], '')
        }
      })
    },
    replaceRangePosition (data) {
      window.Asc.scope.list = data
      window.Asc.plugin.callCommand(function () {
        let list = Asc.scope.list || []
        let oDocument = Api.GetDocument()
        list.forEach(row => {
          oDocument.SearchAndReplace({ searchString: row.str, replaceString: row.newStr }, row.str, row.newStr)
        })
      })
    },
    delMarker (data) {
      let fields = []
      data.forEach(item => {
        fields.push({
          text: '{{' + item.fieldFlag + '}}',
          type: 'field'
        })
      })
      window.Asc.scope.st = fields
      window.Asc.plugin.callCommand(function () {
        let oDocument  = Api.GetDocument()
        let markers = Asc.scope.st.slice(0)
        for (let j = 0; j < markers.length; j++) {
          let marker = markers[j]
          if (marker.type === 'field') {
            oDocument.SearchAndReplace({ searchString: marker.text, replaceString: '' })
          }
        }
      })
    },
    delMarkerGroup (data) {
      this.delMarker(data.fields)
    },
    // excel
    insertCellName (field) {
      window.Asc.scope.field = field
      window.Asc.plugin.callCommand(function () {
        let fieldItem = Asc.scope.field
        let sheetObj = Api.GetActiveSheet()
        let sheetName = sheetObj.GetName()
        let oRange = Api.GetSelection()
        let oCount = oRange.GetCount()
        let params = {
          type: 'onExternalFrameMessage',
          method: 'addCellName'
        }
        if (oCount !== 1) {
          params.data = false
        } else {
          let oAddr = oRange.GetAddress(true, true, '', false)
          let sheetFlag = `${sheetName}!${oAddr}`
          // let name = [fieldItem.fieldName, 'DEF', fieldItem.id].join('')
          // let nameObj = sheetObj.GetDefName(name)
          // console.log('inser cell before = ', name, sheetFlag, nameObj)
          // let result = sheetObj.AddDefName(name, sheetFlag)
          // console.log('insert cell ', name, sheetFlag, result)
          fieldItem.fieldFlag = sheetFlag
          fieldItem.$success = oAddr !== ''
          params.data = fieldItem
        }
        window.top.postMessage(JSON.stringify(params), location.origin)
      })
    },
    getFocusedCell () {
      window.Asc.plugin.callCommand(function () {
        let sheetObj = Api.GetActiveSheet()
        let sheetName = sheetObj.GetName()
        let oRange = Api.GetSelection()
        let params = {
          type: 'onExternalFrameMessage',
          method: 'getFocusedCell'
        }
        let oAddr = oRange.GetAddress(true, true, '', false)
        let sheetFlag = `${sheetName}!${oAddr}`
        params.data = sheetFlag
        window.top.postMessage(JSON.stringify(params), location.origin)
      })
    },
    loadFileFlags (data) {
      window.Asc.scope.list = data
      window.Asc.plugin.callCommand(function () {
        let list = Asc.scope.list || []
        let oDocument = Api.GetDocument()
        let oParCount = oDocument.GetElementsCount()
        let dataMap = {}
        for (let i = 0; i < oParCount; i++) {
          let oPar = oDocument.GetElement(i)
          let ctype = oPar.GetClassType()
          if (ctype === 'table') {
            list.forEach(row => {
              let flag = `{{${row.fieldFlag}}}`
              let rs = oPar.Search(flag)
              for (let i = 0; i < rs.length; i++) {
                let oRange = rs[i]
                if (oRange && oRange.GetText() === flag) {
                  if (dataMap[row.id]) {
                    dataMap[row.id] = dataMap[row.id] + 1
                  } else {
                    dataMap[row.id] = 1
                  }
                }
              }
            })
          } else if (ctype === 'paragraph') {
            let oParText = oPar.GetText()
            list.forEach(row => {
              let count = oParText.split(`{{${row.fieldFlag}}}`).length - 1
              if (dataMap[row.id]) {
                dataMap[row.id] = dataMap[row.id] + count
              } else {
                dataMap[row.id] = count
              }
            })
          }
        }
        let params = {
          type: 'onExternalFrameMessage',
          method: 'loadFieldFlagCount',
          data: dataMap
        }
        window.top.postMessage(JSON.stringify(params), location.origin)
      })
    },
    /**
     * data.sheetName: 要聚焦的sheet名称
     * data.cellName: 要聚焦的cell名称，如C1, D3等
     */
    focusCell (data) {
      window.Asc.scope.data = data
      window.Asc.plugin.callCommand(function () {
        const theData = Asc.scope.data
        const theSheet = Api.GetSheet(theData.sheetName || '')
        if (theSheet) {
          theSheet.SetActive()

          const theCell = theSheet.GetRange(theData.cellName || '')
          if (theCell) {
            theCell.Select()
          }
        }
      })
    },

    getSelectedText (data) {
      window.Asc.scope.data = data
      window.Asc.plugin.callCommand(function () {
        const theData = Asc.scope.data
        const oDoc = Api.GetDocument()
        const oRange = oDoc.GetRangeBySelect()
        if (oRange) {
          const oParas = oRange.GetAllParagraphs()
          // 只能选择一个段落，否则认为不成功
          if (oParas.length === 1) {

            const params = {
              type: 'onExternalFrameMessage',
              method: 'getSelectedText',
              data: {
                id: theData.id,
                text: oRange.GetText()
              }
            }
            window.top.postMessage(JSON.stringify(params), location.origin)
          }
        }
      })
    }
  }

  function receiveMessage (e) {
    let data = e.data ? JSON.parse(e.data) : {}
    if (data.type === 'onExternalPluginMessage') {
      switch (data.method) {
        case 'focus':
          EventMap.focusInDocument(data.data)
          break
        case 'focusTable':
          EventMap.focusTableInDoc(data.data)
          break
        case 'insert':
          EventMap.addMarker(data.data)
          break
        case 'addBookMarker':
          EventMap.addBookMarker(data.data)
          break
        case 'delBookMarker':
          EventMap.deleteBookMarker(data.data)
          break
        case 'delLoopApp':
          EventMap.deleteLoopApp(data.data)
          break
        case 'update':
          EventMap.replaceMarker(data.data)
          break
        case 'findAndInsertMarker':
          EventMap.findAndInsertMarker(data.data)
          break
        case 'addRange':
          EventMap.insertPosition(data.data)
          break
        case 'updateRange':
          EventMap.replaceRangePosition(data.data)
          break
        case 'delRange':
          EventMap.deletePosition(data.data)
          break
        case 'delRangeArray':
          EventMap.deletePositionArray(data.data)
          break
        case 'delQuoteGroup':
          EventMap.deletePositionMarker(data.data)
          break
        case 'remove':
          EventMap.delMarker([ data.data ])
          break
        case 'removeQuestion':
          EventMap.delMarkerGroup(data.data)
          break
        // excel
        case 'addCellName':
          EventMap.insertCellName(data.data)
          break
        case 'loadFieldFlagCount':
          EventMap.loadFileFlags(data.data)
          break
        // 聚焦到某个单元格
        case 'focusCell':
          EventMap.focusCell(data.data)
          break
        // 获取当前选中的单元格
        case 'getFocusedCell':
          EventMap.getFocusedCell()
          break
        // 获取当前选中的文字
        case 'getSelectedText':
          EventMap.getSelectedText(data.data)
          break
      }
    }
  }

  window.addEventListener('message', receiveMessage, false)
})(window, undefined)
