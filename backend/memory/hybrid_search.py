"""
memory/hybrid_search.py
混合检索 - 语义向量 + 关键词匹配
结合向量相似度和关键词匹配，提供更准确的搜索结果
"""

import re
import logging
from typing import List, Tuple, Dict, Set
from dataclasses import dataclass
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from memory.memory_schema import Memory

logger = logging.getLogger(__name__)


@dataclass
class KeywordMatch:
    """关键词匹配结果"""
    memory_id: str
    keyword_hits: int  # 匹配到的关键词数量
    exact_matches: int  # 精确匹配次数
    field_matches: Dict[str, int]  # 各字段匹配情况
    match_score: float  # 综合匹配分数


class KeywordExtractor:
    """关键词提取器"""

    # 停用词（中英文）
    STOP_WORDS = {
        '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '这些', '那些', '什么', '怎么', '为什么', '如何',
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or', 'because', 'until', 'while', 'this', 'that', 'these', 'those', 'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves', 'what', 'which', 'who', 'whom', 'whose', 'this', 'that', 'these', 'those', 'am', 'is', 'are', 'was', 'were', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing'
    }

    @classmethod
    def extract(cls, text: str, min_length: int = 2) -> List[str]:
        """
        从文本中提取关键词
        返回按重要性排序的关键词列表
        """
        if not text:
            return []

        # 预处理
        text = text.lower().strip()

        # 提取中文词汇（2-8个字符）
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,8}', text)

        # 提取英文单词（2个字符以上）
        english_words = re.findall(r'[a-z]{2,}', text)

        # 提取技术术语（如 Python, API, LLM 等）
        tech_terms = re.findall(r'[A-Z]{2,}|[A-Z][a-z]+[A-Z][a-z]*', text)

        # 合并所有候选词
        candidates = chinese_words + english_words + [t.lower() for t in tech_terms]

        # 过滤停用词和过短的词
        keywords = []
        for word in candidates:
            word = word.strip()
            if len(word) >= min_length and word not in cls.STOP_WORDS:
                keywords.append(word)

        # 统计词频并排序
        word_freq = {}
        for word in keywords:
            word_freq[word] = word_freq.get(word, 0) + 1

        # 按频率排序，返回唯一的关键词列表
        sorted_words = sorted(word_freq.items(), key=lambda x: (-x[1], -len(x[0])))
        return [word for word, freq in sorted_words]

    @classmethod
    def extract_phrases(cls, text: str) -> List[str]:
        """
        提取短语（连续的关键词组合）
        """
        if not text:
            return []

        # 提取引号内的内容
        quoted = re.findall(r'["""\']([^"""\']+)["""\']', text)

        # 提取括号内的内容
        bracketed = re.findall(r'[\(\[\{]([^\)\]\}]+)[\)\]\}]', text)

        # 提取连续的中文字符（可能是专有名词）
        chinese_phrases = re.findall(r'[\u4e00-\u9fff]{4,12}', text)

        phrases = quoted + bracketed + chinese_phrases
        return [p.strip() for p in phrases if len(p.strip()) >= 2]


class KeywordMatcher:
    """关键词匹配器"""

    # 字段权重配置
    FIELD_WEIGHTS = {
        'title': 3.0,      # 标题权重最高
        'summary': 2.0,    # 摘要次之
        'tags': 2.5,       # 标签权重较高
        'author': 1.5,     # 作者
        'platform_name': 1.0,  # 平台名
    }

    def __init__(self):
        self.extractor = KeywordExtractor()

    def match(self, query: str, memories: List[Memory]) -> List[KeywordMatch]:
        """
        对查询和记忆列表进行关键词匹配
        返回按匹配分数排序的结果
        """
        # 提取查询关键词
        query_keywords = self.extractor.extract(query)
        query_phrases = self.extractor.extract_phrases(query)

        if not query_keywords and not query_phrases:
            return []

        matches = []
        for memory in memories:
            match = self._match_single(query_keywords, query_phrases, memory)
            if match.keyword_hits > 0:
                matches.append(match)

        # 按匹配分数排序
        matches.sort(key=lambda x: x.match_score, reverse=True)
        return matches

    def _match_single(self, query_keywords: List[str], query_phrases: List[str],
                      memory: Memory) -> KeywordMatch:
        """匹配单个记忆"""
        field_matches = {}
        total_hits = 0
        exact_matches = 0

        # 准备各字段文本
        fields = {
            'title': (memory.title or '').lower(),
            'summary': (memory.summary or '').lower(),
            'tags': ' '.join(memory.tags or []).lower(),
            'author': (memory.author or '').lower(),
            'platform_name': (memory.platform_name or '').lower(),
        }

        # 对每个字段进行匹配
        for field_name, field_text in fields.items():
            if not field_text:
                continue

            field_hits = 0
            field_exact = 0

            # 关键词匹配
            for keyword in query_keywords:
                count = field_text.count(keyword)
                if count > 0:
                    field_hits += count
                    # 精确匹配（完整单词）
                    if f' {keyword} ' in f' {field_text} ' or \
                       field_text.startswith(keyword + ' ') or \
                       field_text.endswith(' ' + keyword) or \
                       field_text == keyword:
                        field_exact += count

            # 短语匹配（权重更高）
            for phrase in query_phrases:
                if phrase.lower() in field_text:
                    field_hits += 2  # 短语匹配给更高权重
                    field_exact += 1

            if field_hits > 0:
                field_matches[field_name] = field_hits
                total_hits += field_hits
                exact_matches += field_exact

        # 计算综合匹配分数
        score = self._calculate_score(field_matches, exact_matches, len(query_keywords))

        return KeywordMatch(
            memory_id=memory.id,
            keyword_hits=total_hits,
            exact_matches=exact_matches,
            field_matches=field_matches,
            match_score=score
        )

    def _calculate_score(self, field_matches: Dict[str, int],
                        exact_matches: int, query_keyword_count: int) -> float:
        """计算综合匹配分数"""
        if not field_matches:
            return 0.0

        # 基础分数：各字段匹配数 * 字段权重
        base_score = 0.0
        for field, hits in field_matches.items():
            weight = self.FIELD_WEIGHTS.get(field, 1.0)
            base_score += hits * weight

        # 精确匹配加成
        exact_bonus = exact_matches * 2.0

        # 覆盖率加成（匹配到的查询词比例）
        coverage = min(len(field_matches) / max(query_keyword_count, 1), 1.0)
        coverage_bonus = coverage * 5.0

        # 字段多样性加成（匹配的字段越多，分数越高）
        diversity_bonus = len(field_matches) * 0.5

        total_score = base_score + exact_bonus + coverage_bonus + diversity_bonus

        # 归一化到 0-1 范围
        return min(total_score / 20.0, 1.0)


class QueryAnalyzer:
    """查询分析器 - 分析查询特征以优化检索策略"""

    # 精确匹配意图关键词
    EXACT_MATCH_PATTERNS = [
        r'"([^"]+)"',  # 引号内的精确短语
        r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b',  # 驼峰命名（如 GitHub, OpenAI）
        r'\b([a-z]+-[a-z]+)\b',  # 连字符连接（如 machine-learning）
    ]

    # 技术术语
    TECH_TERMS = {
        'python', 'javascript', 'typescript', 'java', 'go', 'rust', 'cpp', 'c++',
        'react', 'vue', 'angular', 'node', 'django', 'flask', 'fastapi',
        'docker', 'kubernetes', 'k8s', 'aws', 'azure', 'gcp',
        'github', 'gitlab', 'bitbucket',
        'api', 'rest', 'graphql', 'grpc', 'websocket',
        'database', 'sql', 'nosql', 'mongodb', 'redis', 'postgresql', 'mysql',
        'ai', 'ml', 'machine learning', 'deep learning', 'nlp', 'cv',
        'llm', 'gpt', 'claude', 'openai', 'anthropic',
        'algorithm', 'data structure', 'design pattern',
    }

    @classmethod
    def analyze(cls, query: str) -> Dict[str, any]:
        """分析查询特征"""
        query_lower = query.lower()

        # 提取精确匹配项
        exact_terms = []
        for pattern in cls.EXACT_MATCH_PATTERNS:
            matches = re.findall(pattern, query)
            exact_terms.extend(matches)

        # 检测技术术语
        found_tech_terms = []
        for term in cls.TECH_TERMS:
            if term in query_lower:
                found_tech_terms.append(term)

        # 判断查询类型
        is_exact_query = len(exact_terms) > 0 or len(found_tech_terms) > 0
        is_short_query = len(query) < 20

        # 推荐权重
        if is_exact_query:
            vector_weight = 0.4
            keyword_weight = 0.6
        elif is_short_query:
            vector_weight = 0.5
            keyword_weight = 0.5
        else:
            vector_weight = 0.6
            keyword_weight = 0.4

        return {
            'exact_terms': exact_terms,
            'tech_terms': found_tech_terms,
            'is_exact_query': is_exact_query,
            'is_short_query': is_short_query,
            'vector_weight': vector_weight,
            'keyword_weight': keyword_weight,
        }


class HybridSearcher:
    """
    混合检索器
    结合语义向量检索和关键词匹配
    """

    def __init__(self):
        self.keyword_matcher = KeywordMatcher()
        self.query_analyzer = QueryAnalyzer()

    def search(
        self,
        query: str,
        query_embedding: List[float],
        memories: List[Memory],
        vector_scores: Dict[str, float],
        top_k: int = 10,
        vector_weight: float = None,  # 自动检测
        keyword_weight: float = None,  # 自动检测
    ) -> List[Tuple[Memory, float]]:
        """
        混合检索

        Args:
            query: 原始查询文本
            query_embedding: 查询的向量表示
            memories: 候选记忆列表
            vector_scores: 向量检索分数 {memory_id: score}
            top_k: 返回结果数量
            vector_weight: 向量分数权重（None则自动检测）
            keyword_weight: 关键词分数权重（None则自动检测）

        Returns:
            [(Memory, hybrid_score), ...] 按混合分数排序
        """
        if not memories:
            return []

        # 分析查询特征
        query_analysis = self.query_analyzer.analyze(query)

        # 自动确定权重
        if vector_weight is None:
            vector_weight = query_analysis['vector_weight']
        if keyword_weight is None:
            keyword_weight = query_analysis['keyword_weight']

        logger.info(f"[HybridSearch] 查询分析: exact={query_analysis['is_exact_query']}, "
                   f"权重: vector={vector_weight}, keyword={keyword_weight}")

        # 步骤1: 关键词匹配
        keyword_matches = self.keyword_matcher.match(query, memories)
        keyword_scores = {m.memory_id: m.match_score for m in keyword_matches}

        # 步骤2: 融合分数（带boost策略）
        results = []
        for memory in memories:
            mem_id = memory.id

            # 获取向量分数
            vec_score = vector_scores.get(mem_id, 0.0)

            # 获取关键词分数
            key_score = keyword_scores.get(mem_id, 0.0)

            # 特殊boost：如果包含精确匹配的技术术语
            boost = 1.0
            if query_analysis['tech_terms']:
                memory_text = f"{memory.title} {memory.summary} {' '.join(memory.tags or [])}".lower()
                for term in query_analysis['tech_terms']:
                    if term in memory_text:
                        boost += 0.1  # 每个匹配术语增加10%

            # 混合分数计算
            if vec_score > 0 and key_score > 0:
                # 两者都有，按权重融合
                hybrid_score = (vec_score * vector_weight + key_score * keyword_weight) * boost
            elif vec_score > 0:
                # 只有向量分数
                hybrid_score = vec_score * 0.85 * boost
            elif key_score > 0:
                # 只有关键词分数（可能是向量没召回但关键词匹配）
                hybrid_score = key_score * 0.6 * boost
            else:
                continue

            results.append((memory, hybrid_score))

        # 步骤3: 排序并返回
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def rerank(
        self,
        query: str,
        vector_results: List[Tuple[Memory, float]],
        top_k: int = 10,
    ) -> List[Tuple[Memory, float]]:
        """
        对向量检索结果进行重排序（加入关键词匹配）
        用于在已有向量检索结果基础上优化排序
        """
        if not vector_results:
            return []

        memories = [m for m, _ in vector_results]
        vector_scores = {m.id: s for m, s in vector_results}

        # 构建假embedding（不使用）
        dummy_embedding = []

        return self.search(
            query=query,
            query_embedding=dummy_embedding,
            memories=memories,
            vector_scores=vector_scores,
            top_k=top_k,
            vector_weight=0.5,
            keyword_weight=0.5,
        )


# 便捷函数
def hybrid_search(
    query: str,
    query_embedding: List[float],
    memories: List[Memory],
    vector_scores: Dict[str, float],
    top_k: int = 10,
) -> List[Tuple[Memory, float]]:
    """混合检索便捷函数"""
    searcher = HybridSearcher()
    return searcher.search(query, query_embedding, memories, vector_scores, top_k)


def extract_keywords(text: str) -> List[str]:
    """提取关键词便捷函数"""
    return KeywordExtractor.extract(text)


def rerank_by_keywords(
    query: str,
    vector_results: List[Tuple[Memory, float]],
    top_k: int = 10,
) -> List[Tuple[Memory, float]]:
    """关键词重排序便捷函数"""
    searcher = HybridSearcher()
    return searcher.rerank(query, vector_results, top_k)
