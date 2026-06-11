import docx
from docx.oxml.ns import qn
import sys

def extract_tracked_changes(docx_path):
    doc = docx.Document(docx_path)
    
    print(f"Reviewing changes in: {docx_path}\n")
    
    change_count = 0
    
    for i, paragraph in enumerate(doc.paragraphs):
        p_element = paragraph._element
        
        # Check if paragraph has any ins or del elements
        ins_elements = p_element.xpath('.//w:ins')
        del_elements = p_element.xpath('.//w:del')
        
        if ins_elements or del_elements:
            change_count += 1
            print(f"--- Paragraph {i+1} ---")
            
            # We want to show the context of the change.
            # We'll iterate through all children of the paragraph and identify runs, insertions, and deletions.
            
            output = []
            
            # Use a more direct way to iterate all text-bearing elements in order
            # This is a bit tricky with oxml/lxml but we can iterate the tree
            
            # We'll use a recursive function to collect text with markers
            def get_marked_text(element):
                text_parts = []
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                for child in element:
                    tag = child.tag
                    if tag.endswith('}ins'):
                        # Insertion
                        ins_text = "".join(get_marked_text(child))
                        text_parts.append(f"[[NEW: {ins_text}]]")
                    elif tag.endswith('}del'):
                        # Deletion
                        # Deletions use w:delText instead of w:t
                        del_texts = child.xpath('.//w:delText', namespaces=ns)
                        del_text = "".join(t.text for t in del_texts if t.text)
                        text_parts.append(f"[[OLD: {del_text}]]")
                    elif tag.endswith('}t'):
                        # Normal text (if not inside ins/del)
                        if child.text:
                            text_parts.append(child.text)
                    elif tag.endswith('}delText'):
                        # This should be handled by the }del block above, but just in case
                        if child.text:
                            text_parts.append(child.text)
                    else:
                        # Recurse into other elements (like w:r)
                        text_parts.extend(get_marked_text(child))
                return text_parts

            para_text = "".join(get_marked_text(p_element))
            print(para_text)
            print()

    if change_count == 0:
        print("No tracked changes found in paragraphs.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_changes.py <path_to_docx>")
    else:
        extract_tracked_changes(sys.argv[1])
